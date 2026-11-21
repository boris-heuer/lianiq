"""CAP-0171 contract.md §6: ``PackJobRunner`` and ``JobListener`` (one job at a time).

The runner drives a ``PackInstaller`` on an executor, exposes the running ``JobView``,
throttles progress to at most ten calls per second and reports a reason on failure.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from pathlib import Path

import pytest
from _install_fixtures import ACCEPTED, MT_V1, FakeTransport, catalog_of, mt_pack_entry
from _install_fixtures import installer as real_installer

from lianiq.packs.errors import (
    ConnectionUnavailable,
    InstallCancelled,
    InsufficientSpace,
    JobBusy,
    PackFileError,
    PackInUse,
)
from lianiq.packs.installer import InstallResult
from lianiq.packs.jobs import JOB_CANCELLED, JobPhase, JobView, PackJobRunner
from lianiq.packs.sources import DownloadSource, ImportSource


class Immediate(Executor):
    def submit(self, fn, /, *args, **kwargs) -> Future:
        future: Future = Future()
        future.set_result(fn(*args, **kwargs))
        return future


class Listener:
    def __init__(self) -> None:
        self.progress_views: list[JobView] = []
        self.results: list[InstallResult | None] = []
        self.failures: list[tuple[str, str]] = []
        self.done = threading.Event()

    def progress(self, view: JobView) -> None:
        self.progress_views.append(view)

    def finished(self, result: InstallResult | None) -> None:
        self.results.append(result)
        self.done.set()

    def failed(self, pack_id: str, reason: str) -> None:
        self.failures.append((pack_id, reason))
        self.done.set()


class FakeInstaller:
    def __init__(self, *, error: Exception | None = None, steps: int = 3) -> None:
        self.error, self.steps = error, steps
        self.gate = threading.Event()
        self.gate.set()
        self.seen: list[JobView | None] = []
        self.runner: PackJobRunner | None = None
        self.space_checked: list[str] = []

    def check_space(self, pack) -> None:
        self.space_checked.append(pack.id)

    def install(self, pack, source, accepted, progress, cancel):
        for step in range(self.steps):
            progress(JobPhase.TRANSFER, step + 1, self.steps)
            if self.runner is not None:
                self.seen.append(self.runner.current)
        self.gate.wait(5)
        if cancel.cancelled:
            raise InstallCancelled()
        if self.error is not None:
            raise self.error
        return InstallResult(pack.id, pack.version, source.record_source)

    def remove(self, pack) -> None:
        if self.error is not None:
            raise self.error


@pytest.fixture
def pack(tmp_path: Path):
    return catalog_of(tmp_path / "c", mt_pack_entry()).get("mt-a")


def source() -> DownloadSource:
    return DownloadSource(FakeTransport({}))


def test_a_job_reports_progress_and_its_result(pack) -> None:
    fake = FakeInstaller()
    runner = PackJobRunner(fake, Immediate(), monotonic=iter(range(100)).__next__)
    fake.runner = runner
    listener = Listener()
    runner.start(pack, "install", source(), ACCEPTED, listener)

    assert listener.results == [InstallResult("mt-a", "1", "download")]
    assert [v.done for v in listener.progress_views] == [1, 2, 3]
    assert fake.seen[-1] == JobView("mt-a", "install", JobPhase.TRANSFER, 3, 3)
    assert runner.current is None and fake.space_checked == ["mt-a"]


def test_progress_is_throttled_to_ten_per_second(pack) -> None:
    ticks = iter([0.0, 0.01, 0.05, 0.099, 0.1, 0.15, 0.25, 0.26] + [9.0] * 50)
    fake = FakeInstaller(steps=7)
    runner = PackJobRunner(fake, Immediate(), monotonic=lambda: next(ticks))
    listener = Listener()
    runner.start(pack, "update", source(), ACCEPTED, listener)
    assert [v.done for v in listener.progress_views] == [1, 5, 7]


def test_a_second_job_is_refused_while_one_runs(pack) -> None:
    fake = FakeInstaller()
    fake.gate.clear()
    with ThreadPoolExecutor(max_workers=2) as executor:
        runner = PackJobRunner(fake, executor)
        listener = Listener()
        runner.start(pack, "install", source(), ACCEPTED, listener)
        assert runner.current is not None and runner.current.pack_id == "mt-a"
        with pytest.raises(JobBusy):
            runner.start(pack, "remove", None, None, Listener())
        fake.gate.set()
        assert listener.done.wait(5)
    assert runner.current is None


def test_cancel_reaches_the_running_job(pack) -> None:
    fake = FakeInstaller()
    fake.gate.clear()
    with ThreadPoolExecutor(max_workers=1) as executor:
        runner = PackJobRunner(fake, executor)
        listener = Listener()
        runner.start(pack, "install", source(), ACCEPTED, listener)
        runner.cancel()
        fake.gate.set()
        assert listener.done.wait(5)
    assert listener.failures == [("mt-a", JOB_CANCELLED)]
    assert isinstance(runner.last_error, InstallCancelled)


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (PackFileError("file config.json is missing"), "file config.json is missing"),
        (ConnectionUnavailable("huggingface.co"), "no connection to huggingface.co"),
        (InsufficientSpace(10, 5), "not enough disk space"),
        (RuntimeError("boom with a secret path"), "unexpected error: RuntimeError"),
    ],
)
def test_failures_reach_the_listener_with_a_reason(pack, error, reason) -> None:
    runner = PackJobRunner(FakeInstaller(error=error), Immediate())
    listener = Listener()
    runner.start(pack, "install", ImportSource(Path("x.zip")), ACCEPTED, listener)
    assert listener.failures == [("mt-a", reason)]
    assert runner.last_error is error and runner.current is None


def test_remove_finishes_without_a_result(pack) -> None:
    runner = PackJobRunner(FakeInstaller(), Immediate())
    listener = Listener()
    runner.start(pack, "remove", None, None, listener)
    assert listener.results == [None]


def test_the_guard_refuses_update_and_remove_before_any_work(pack) -> None:
    calls: list[tuple[str, str]] = []

    def guard(target, operation: str) -> None:
        calls.append((target.id, operation))
        if operation != "install":
            raise PackInUse("Conversation")

    fake = FakeInstaller()
    runner = PackJobRunner(fake, Immediate(), guard=guard)
    for operation, src in (("update", source()), ("remove", None)):
        with pytest.raises(PackInUse):
            runner.start(pack, operation, src, ACCEPTED, Listener())
    listener = Listener()
    runner.start(pack, "install", source(), ACCEPTED, listener)
    assert listener.results and calls == [
        ("mt-a", "update"),
        ("mt-a", "remove"),
        ("mt-a", "install"),
    ]


def test_insufficient_space_stops_the_job_before_it_starts(pack) -> None:
    class Full(FakeInstaller):
        def check_space(self, pack) -> None:
            raise InsufficientSpace(100, 1)

    runner = PackJobRunner(Full(), Immediate())
    listener = Listener()
    with pytest.raises(InsufficientSpace):
        runner.start(pack, "install", source(), ACCEPTED, listener)
    assert runner.current is None and listener.results == listener.failures == []


@pytest.mark.parametrize(
    ("operation", "src"), [("install", None), ("frobnicate", None), ("update", None)]
)
def test_invalid_requests_are_refused(pack, operation, src) -> None:
    runner = PackJobRunner(FakeInstaller(), Immediate())
    with pytest.raises(ValueError):
        runner.start(pack, operation, src, ACCEPTED, Listener())
    assert runner.current is None


def test_ac27_job_logs_name_only_pack_fields(tmp_path, pack, caplog) -> None:
    caplog.set_level(logging.INFO, logger="lianiq.packs")
    runner = PackJobRunner(real_installer(tmp_path / "p"), Immediate())
    payloads = {item.url: MT_V1[item.path] for item in pack.files}
    runner.start(pack, "install", DownloadSource(FakeTransport(payloads)), ACCEPTED, Listener())
    runner.start(pack, "update", ImportSource(tmp_path / "missing.zip"), ACCEPTED, Listener())

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "pack_id=mt-a" in text and "operation=install" in text and "state=succeeded" in text
    assert "state=failed" in text and "error=PackFileError" in text
    assert str(tmp_path) not in text and "example.test" not in text


def test_c4_a_failed_submit_leaves_the_runner_free(pack) -> None:
    class Broken(Executor):
        def submit(self, fn, /, *args, **kwargs) -> Future:
            raise RuntimeError("cannot schedule new futures after shutdown")

    runner = PackJobRunner(FakeInstaller(), Broken())
    with pytest.raises(RuntimeError):
        runner.start(pack, "install", source(), ACCEPTED, Listener())
    assert runner.current is None
    runner._executor = Immediate()  # type: ignore[attr-defined]
    listener = Listener()
    runner.start(pack, "install", source(), ACCEPTED, listener)
    assert listener.results
