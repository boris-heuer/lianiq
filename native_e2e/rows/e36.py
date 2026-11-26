"""E-36: the two route tests, measured on the cables (CAP-0166 0166-E-03; AC-04..AC-06).

On the app E-34 opened (``rows.cb``), with the four roles of a ready bridge (call speaker cable
"CABLE-B Output"), "CABLE Output" (the headset) and "CABLE-A Output" (the call app's
microphone) are recorded while each test plays:

- **Test · Call → you** plays the German route-test phrase into *Your headphones*: speech on
  the headset, none on cable A; the row shows "Did you hear it?"; **Yes** → *Test passed*.
- **Test · You → call** plays the Mandarin phrase into the call microphone cable: speech on
  cable A, none on the headset; "Did your partner hear it?"; **Yes** → *Test passed*.

Throughout, both lane status lines stay *Stopped* and a test row never shows a lane activity
(*Running*). Then *Your headphones* is changed to "CABLE-B Input" and back: *Call → you* reads
*Not tested* again, *You → call* keeps *Test passed*. Masked screenshots after each answer.
Only spans and counts are stored; a test that does not play is ``fail``, never retried.
"""

from __future__ import annotations

import time
from typing import Any

from native_e2e.context import CABLE_NAMES, RunContext
from native_e2e.evidence.model import Check, Method, Row
from native_e2e.rows import cb, ui
from native_e2e.rows.common import blocked_row, check, make_row


def _test(nodes, path_name: str) -> str | None:
    return cb.prefixed(nodes, cb.strings().CB_TEST_ROW, path_name)


def _one_test(ctx, app, recs, path: str, checks: list[Check], seen: dict) -> bool:
    """Run the route test of ``path`` ("out" or "in"); record where its phrase was heard."""
    t = cb.strings()
    outbound = path == "out"
    name = t.CB_PATH_OUT_NAME if outbound else t.CB_PATH_IN_NAME
    question = t.CB_Q_OUT if outbound else t.CB_Q_IN
    test = cb.button(app.nodes(), f"{t.CB_TEST} · {name}")
    if test is None or not test.enabled:
        checks.append(check(f"{path}-test-enabled", False))
        return False
    began = time.perf_counter()
    app.press(test)

    def asked() -> bool:
        nodes = app.nodes()
        seen["lanes"].update(cb.lanes(nodes))
        seen["tests"].add(_test(nodes, name))
        return _test(nodes, name) == question

    if not ui.waited(checks, f"{path}-test-asks", asked, ui.MODEL_TIMEOUT_S):
        return False
    ended = time.perf_counter()
    cable, headset = (recs["a"].span(began, ended), recs["h"].span(began, ended))
    checks += [
        check(f"{path}-test-on-call-cable", (cable is not None) == outbound),
        check(f"{path}-test-in-headset", (headset is not None) != outbound),
    ]
    app.press(cb.button(app.nodes(), f"{t.CB_YES} · {name}"))
    passed = lambda: _test(app.nodes(), name) == t.CB_T_PASSED
    if not ui.waited(checks, f"{path}-test-passed", passed):
        return False
    shot, artifact = cb.shot(ctx, app, f"screens/e36-{path}.png", f"screenshot-{path}")
    checks.append(shot)
    recs["artifacts"].append(artifact)
    return True


def _reset_by_change(app: Any, names: dict[str, str], checks: list[Check]) -> None:
    t = cb.strings()
    label = t.CB_ROLE_HEADPHONES
    changed = cb.choose(app, label, names["b_in"]) and cb.choose(app, label, names["headphones"])

    def reset() -> bool:
        nodes = app.nodes()
        return (_test(nodes, t.CB_PATH_IN_NAME), _test(nodes, t.CB_PATH_OUT_NAME)) == (
            t.CB_T_NOT_TESTED,
            t.CB_T_PASSED,
        )

    if not changed:
        checks.append(check("headphones-changed-and-back", False))
        return
    ui.waited(checks, "change-resets-call-to-you-only", reset)


def e36(ctx: RunContext) -> Row:
    names = cb.prepare(ctx)
    if names is None:
        return blocked_row("E-36", cb.BLOCKED)
    t = cb.strings()
    app = cb.app(ctx)
    checks: list[Check] = []
    recs: dict[str, Any] = {"artifacts": []}
    seen: dict[str, set] = {"lanes": set(), "tests": set()}
    if cb.page(app, checks) and cb.assign(app, names, checks):
        with cb.Recorder(cb.A_OUT) as cable, cb.Recorder(CABLE_NAMES[1]) as headset:
            recs.update(a=cable, h=headset)
            done = _one_test(ctx, app, recs, "in", checks, seen) and _one_test(
                ctx, app, recs, "out", checks, seen
            )
        if done:
            lane_texts = {
                t.CB_LANE_STARTING,
                t.CB_LANE_LISTENING,
                t.CB_LANE_TRANSLATING,
                t.CB_LANE_SPEAKING,
            }
            checks += [
                check("lanes-stayed-stopped", seen["lanes"] == {t.CB_LANE_STOPPED}),
                check("test-row-never-running", not seen["tests"] & lane_texts),
            ]
            _reset_by_change(app, names, checks)
    return make_row(
        "E-36", checks, recs["artifacts"], reason="route-tests", method=Method.VIRTUAL_DEVICE
    )
