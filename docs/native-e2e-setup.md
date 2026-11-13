# Native E2E VM setup

This guide sets up the disposable Windows 11 VM that runs the automated native rows of the
`native-e2e` workflow (CAP-0174 `native-test-automation`). It is written for the product
owner (PO) who owns the workstation and the repository. Every step on the workstation is a PO
step: agents write these scripts but never run Hyper-V, the image build, the run script or
any elevated command.

The VM runs only during a run. It is reverted to the checkpoint `clean` after every run, holds
no reusable credential and reaches only GitHub, through an allow-list proxy on the host.

## Prerequisites

| Item | What to do |
| --- | --- |
| Windows host with Hyper-V | Windows 11 Pro or Enterprise, 64-bit, virtualization enabled in the firmware. Enable Hyper-V from an elevated PowerShell with `Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All` and restart. The VM needs 4 vCPUs, 8 GB RAM and up to 128 GB of disk. |
| Windows 11 Enterprise evaluation ISO | Download the ISO yourself from the Microsoft Evaluation Center and read its evaluation terms. The evaluation runs for 90 days; the image is then rebuilt (see [The 90-day rebuild](#the-90-day-rebuild)). Prefer the English (United States) ISO; the answer file uses the built-in `Administrator` account name. |
| VB-Cable package | Download the VB-Cable driver pack (one cable, for example `VBCABLE_Driver_Pack45.zip`) yourself from VB-Audio Software and read its licence first. See [VB-Cable licence](#vb-cable-licence). |
| Lianiq checkout | A clone of `boris-heuer/lianiq` at the commit you want the image built from, with `scripts\setup.ps1` already run so that `.venv` holds the locked dependency set and `scripts\download_models.py` can run. |
| Git and GitHub CLI | `git` and `gh` on `PATH`; `gh auth login` with **your own** account. Only the host uses this login: to download the runner package and to request one JIT runner configuration per run. It never enters the VM. |
| GitHub environment | In the lianiq repository settings create the environment `native-e2e` with yourself as the required reviewer (e2e plan S-02). |

### VB-Cable licence

VB-Cable is donationware from VB-Audio Software. Lianiq uses one cable in the test VM only, so
that the E-03 and E-11 rows have a capture device and the test phrase can be played into it.
This use is private and non-commercial (PO decision of 2026-11-11). Before any commercial use
the licence must be clarified with VB-Audio. The package is never committed to this
repository; the image build records its SHA-256 in `image.json`.

## Build the image

Run once, and again for every rebuild, from an elevated PowerShell in the lianiq checkout:

```powershell
.\tools\native-e2e\host\New-NativeE2eImage.ps1 `
    -IsoPath D:\iso\Win11_Enterprise_Eval.iso `
    -VbCablePackage D:\downloads\VBCABLE_Driver_Pack45.zip
```

Add `-Replace` for a rebuild: it deletes the previous VM `lianiq-native-e2e` and its disk. The
defaults put everything under `C:\ProgramData\lianiq-native-e2e` and use the internal switch
`lianiq-e2e` with the host at `192.168.250.1/24`, the guest at `192.168.250.10` and the proxy on
port 8080. If that subnet is already used on your network, pass `-HostAddress`,
`-GuestAddress` and `-PrefixLength`.

What the script does:

1. Checks elevation, Hyper-V, `.venv` (Python 3.12, 64-bit), `git` and your `gh` login.
2. Downloads every input on the host: the Python 3.12.10 installer (size and Python Software
   Foundation signature checked), the wheels of `requirements-lock.txt` and
   [`native_e2e/requirements-native-lock.txt`](../native_e2e/requirements-native-lock.txt)
   with `pip download --require-hashes`, the models with `scripts\download_models.py`, and the
   latest GitHub Actions runner package for Windows x64 (checked against its release digest).
3. Creates the internal switch without NAT, gives the host its switch address and adds the
   host firewall rule `lianiq-native-e2e-proxy` (inbound TCP to the proxy port from the guest
   address only).
4. Applies the Enterprise evaluation edition offline to a new VHDX, writes the answer file
   ([`autounattend.xml`](../tools/native-e2e/guest/autounattend.xml) with a random one-time
   build password) and copies the inputs and guest scripts into it.
5. Creates the generation 2 VM: 4 vCPUs, 8 GB static memory, Secure Boot, virtual TPM,
   1920×1080, no automatic checkpoints, one network adapter with MAC spoofing off and the
   adapter ACLs (deny all, allow only TCP to the proxy port on the host).
6. Starts the VM. The guest signs in once as the build account and runs
   [`provision.ps1`](../tools/native-e2e/guest/provision.ps1) with no network: Python 3.12 for
   all users, the image environment from the wheels, the models (read-only), VB-Cable, the test
   phrase, the runner package (not a service), the SYSTEM admin helper, the logon task, WFP
   auditing, the machine-wide `https_proxy`, the non-admin auto-logon user `e2e` and
   `C:\ProgramData\lianiq-e2e\image.json`. It disables the build account, deletes the answer
   file and shuts down.
7. Reads the provisioning result from the disk, takes checkpoint `clean` and prints the values
   to record.

**PO step during the build:** if Windows asks whether to trust the VB-Audio driver publisher,
open the VM console (Hyper-V Manager › `lianiq-native-e2e` › **Connect**) and confirm it. The
build waits up to 15 minutes for the two cable endpoints `CABLE Input` and `CABLE Output`.

**Record the image (e2e plan S-04):** copy the printed image id, Windows build and host OS
build into the capability's `verification-report.md`. The same values stay in
`C:\ProgramData\lianiq-native-e2e\image.json` and the guest copy.

### Image contents

`image.json` (schema `lianiq-native-e2e-image/v1`) holds: `image_id` and `image`
(`win11-native-e2e@<image-id>`), `windows_build` (`CurrentBuild.UBR`), `windows_edition`,
`host_os_build`, `source_commit`, `python`, `interpreter` (the base interpreter
`C:\Program Files\Python312\python.exe`), `venv`, `models_dir`, `models_manifest_sha256`,
`test_phrase` (`path` and `sha256`), `audio`, `test_user`, `runner_dir`, `https_proxy` and
the SHA-256 of every build input. The test phrase "Guten Morgen, das ist ein Test." is
generated in the guest by
[`make_test_phrase.py`](../native_e2e/data/make_test_phrase.py) with the German Piper voice;
the WAV is never committed.

Guest folders under `C:\ProgramData\lianiq-e2e` are read-only for the test user except
`admin\requests` (admin helper requests), `jit` (the JIT configuration), `state` (run state,
such as the S-01 run marker, and the logon log) and `venv` (the job installs the checked-out
project there).

## Check the isolation (e2e plan E-01)

Once per image, before the first run, start the VM from Hyper-V Manager, let it sign in as
`e2e`, open PowerShell in the VM console and run:

```powershell
Test-NetConnection 192.168.250.1 -Port 445
Test-NetConnection <a LAN address> -Port 80
Invoke-WebRequest https://example.com -Proxy $env:https_proxy -UseBasicParsing
Invoke-WebRequest https://api.github.com -Proxy $env:https_proxy -UseBasicParsing
whoami /groups
```

Start the proxy first in a second elevated host window with the host Python recorded in
`host.json`:
`& <host_python> -I .\tools\native-e2e\host\egress-proxy.py --listen 192.168.250.1`.
Windows PowerShell 5.1 does not read `https_proxy` by itself, hence `-Proxy`; the runner and
Python do. Pass only when the host, the LAN address and example.com fail, api.github.com succeeds and
`whoami /groups` lists no Administrators group. Record the output with addresses replaced by
`<lan>`. Then stop the proxy, shut the VM down and revert it to `clean` in Hyper-V Manager
(or start the next run, which reverts it).

## Per-run steps

1. **Dispatch.** Start the `native-e2e` workflow for a 40-hex `commit` (GitHub UI, or a
   Factory agent through the Gateway). The job waits for the environment approval.
2. **Run the host script** from an elevated PowerShell in the checkout:

   ```powershell
   .\tools\native-e2e\host\Invoke-NativeE2eRun.ps1
   ```

   It checks the switch, the absence of NAT and the adapter ACLs, reverts the VM to `clean`,
   starts [`egress-proxy.py`](../tools/native-e2e/host/egress-proxy.py), starts the VM, waits
   for the Hyper-V heartbeat, requests a one-job JIT runner configuration with your `gh` login
   (labels `self-hosted`, `windows`, `win11-native-e2e`) and copies it into the guest with
   `Copy-VMFile`. The `e2e` logon task starts the runner with it
   ([`runner-logon.ps1`](../tools/native-e2e/guest/runner-logon.ps1)).
3. **Approve** the run in GitHub (next section).
4. **Wait.** The job runs the rows; the runner exits after its one job. The host script then
   shuts the VM down, reverts it to `clean`, stops the proxy and prints the run URL and the
   SHA-256 of `native-evidence.json`. A copy of the artifact stays under
   `C:\ProgramData\lianiq-native-e2e\runs\<run-id>`.

The proxy log of every run is `C:\ProgramData\lianiq-native-e2e\logs\egress-proxy-<time>.log`:
one line per tunnel (host name only) and per refusal with its reason.

## Approve the run

Open the run in lianiq › Actions › `native-e2e`. It shows **Review deployments** for the
environment `native-e2e`. Check that the commit is the one you expect, then approve. Approve
only runs that you or the requesting agent dispatched for a known commit; reject anything else.
A changed screenshot is signed off later from the run summary and `compare/application-ui.png`.

## The 90-day rebuild

The evaluation image expires 90 days after the build; the image id starts with the build date
(`yyyyMMdd-…`). Rebuild before then with `New-NativeE2eImage.ps1 -Replace` and a current
evaluation ISO, record the new image values (S-04) and check the isolation again (E-01). The
image is kept until the next rebuild (teardown T-03). After a rebuild the first SHOT row is
expected to be `pending` until you accept a screenshot from the new image. Runs are refused
while the image is expired because the runner never comes online.

## Diagnostic: `-NoRevert`

`Invoke-NativeE2eRun.ps1 -NoRevert` skips the revert to `clean` at the start and at the end of
that invocation (AC-16, e2e plan E-09). Run it twice in a row: the first run leaves its run
marker on the disk, and the second run's S-01 must fail with `not-clean-snapshot`. Afterwards
start a normal run (or revert to `clean` in Hyper-V Manager) to restore the VM.

## Assumptions checked at first build

The scripts rely on these points, which no test on a developer machine can prove. The PO
confirms them during the first image build (S-03) and the isolation check (E-01); a failure
stops the build or the run instead of passing silently.

- The VB-Cable installer accepts the silent flags `-i -h`; otherwise its window or a driver
  prompt appears in the VM console and the build waits for the two cable endpoints.
- The guest trusts the Authenticode chains of the Python and VB-Cable installers offline (the
  root certificates ship with the evaluation image); otherwise provisioning stops at the
  signature check.
- The provisioning disk, mounted read-only on the host after the build, gets a drive letter
  so that `provision-result.json` and `image.json` can be read.
- The integration-service ids of the guest service interface and the heartbeat, the stored
  `Protocol` value of the allow ACL (`6` or `TCP`), the unscoped values of the deny ACLs and
  the OOBE skip settings behave as written in the scripts.
- Spec section 9: WFP events 5156/5157 name the interpreter path (item 1); blocking the base
  interpreter blocks the app started from the image environment (item 2); VB-Cable installs
  with at most one consent click (item 3); the Actions artifact hosts fit the allow-list, as
  the first run's proxy log shows (item 6).

## Troubleshooting

| Symptom | Cause and action |
| --- | --- |
| The build stops at "guest provisioning" | Open the VM console. A visible VB-Cable prompt needs your confirmation. Otherwise read `C:\ProgramData\lianiq-native-e2e\logs\<image-id>\provision.log` after the timeout; the script names the failed step. Fix the cause and rebuild with `-Replace`. |
| `pip download` fails | A locked wheel is missing for Windows x64 / Python 3.12, or the network failed. Rerun the build; a changed lock is fixed by pull request, never by unpinning. |
| "The VM adapter ACLs differ" or "A NetNat covers …" | The network no longer matches the recipe. Remove the extra NAT or rebuild the image; never run with a routed or opened network. |
| "the runner did not come online within 10 minutes" | Infrastructure fault. Check the proxy log for refusals and the guest log `C:\ProgramData\lianiq-e2e\state\runner-logon.log`. You may start the host script once more. If GitHub rejects an outdated runner version, rebuild the image. |
| The job never starts | The run waits for your approval, or the dispatch used another commit. The host script stops after `-JobTimeoutMinutes` (default 180), removes the JIT runner and reverts the VM. |
| A refusal for a GitHub host appears in the proxy log | The allow-list misses an Actions host (spec item 6). Add it to [`egress-allowlist.txt`](../tools/native-e2e/host/egress-allowlist.txt) by pull request; never add a wildcard for a whole domain. |
| S-01 is `fail` with `not-clean-snapshot` | The VM was not reverted. Start a normal run without `-NoRevert`. |
| The run script exits with code 3 | A cleanup step failed (runner removal, VM stop, proxy stop or revert); the output names it. Finish it in Hyper-V Manager: turn the VM off and apply checkpoint `clean`. |
| The VM is left running after an error | Turn it off and apply checkpoint `clean` in Hyper-V Manager (teardown T-01). |

## Security boundary

- **Trigger and approval:** the workflow runs only on `workflow_dispatch`, and every run waits
  for your approval in the environment `native-e2e`.
- **Credentials:** the VM holds no GitHub credential. The JIT configuration is requested with
  your host login, copied host-to-guest with `Copy-VMFile`, deleted by the logon script after
  reading and invalid after its one job. The `e2e` auto-logon password is random and exists
  only inside the VM.
- **Network:** an internal Hyper-V switch without NAT. Host-enforced adapter ACLs deny all
  guest traffic except TCP to the proxy port on the host's switch address; the guest has no
  gateway and no DNS server. The proxy relays only HTTPS `CONNECT` to port 443 for host names
  in `egress-allowlist.txt`, resolves them on the host, refuses private, loopback and
  link-local addresses and logs every refusal. There is no TLS interception, no host share
  and no clipboard or drive redirection (blocked by policy in the guest).
- **Privileges:** the test user `e2e` is not an administrator. Admin actions go only through
  the SYSTEM admin helper ([`admin-helper.ps1`](../tools/native-e2e/guest/admin-helper.ps1)),
  which executes exactly `firewall-block-app <path>`, `firewall-unblock-app` and
  `wfp-count <path> <since>`. `<path>` must equal the `interpreter` in `image.json`, and the
  firewall rule name is fixed. Any other verb or path is rejected and logged in
  `C:\ProgramData\lianiq-e2e\admin\helper.log`.
- **State:** every run starts from and returns to checkpoint `clean`; the S-01 run marker
  proves the revert. Nothing leaves the VM except the redacted, hashed artifact uploaded by the
  job.
- **Host changes:** the build adds the internal switch `lianiq-e2e`, its host address, the
  inbound firewall rule `lianiq-native-e2e-proxy` and the VM. To remove everything, delete the
  VM in Hyper-V Manager, then run `Remove-VMSwitch lianiq-e2e`,
  `Remove-NetFirewallRule -Name lianiq-native-e2e-proxy` and delete
  `C:\ProgramData\lianiq-native-e2e`.
