# Self-hosted runner

All workflows (`measure.yml`, `test.yml`, `backfill.yml`) run on our own Linux VM with
`runs-on: [self-hosted, linux]`. This runbook covers what the VM needs and how to register a runner for this repo.

## 1. Inspect the VM

**CPU architecture** (selects the runner download):
```bash
uname -m        # x86_64 → x64,  aarch64 → arm64
```

**OS** (`actions/setup-python` downloads prebuilt Python only for Ubuntu):
```bash
cat /etc/os-release
```

**Existing runners** (e.g. the one serving another repo):
```bash
systemctl list-units --all 'actions.runner.*'                 # service name = actions.runner.<owner>-<repo>.<name>
ps -eo user,pid,args | grep -E '[R]unner\.(Listener|Worker)'  # running process + its path
sudo find / -name .runner -not -path '/proc/*' 2>/dev/null    # each hit is a runner install directory
```
For each directory found:
```bash
cat <dir>/.runner          # gitHubUrl shows which repo it serves; agentName is its name
cat <dir>/.service         # systemd unit name (if installed as a service)
```

An existing runner **cannot be reused**: on a personal account a runner is registered to exactly one repo.
Install a second one in its own directory (step 3). Both can run side by side on one VM.

## 2. Make the VM compatible

| Need | Why | Check | Fix |
|---|---|---|---|
| Ubuntu (22.04/24.04) | `setup-python` / `setup-node` download prebuilt toolchains | `cat /etc/os-release` | Other distros: install Python 3.12 and Node 22 yourself and tell us to drop the setup actions |
| `git`, `curl`, `tar` | checkout, runner download | `git --version` | `sudo apt-get install -y git curl tar` |
| Playwright system libraries for Firefox + Chromium | browser probes (workflow no longer installs them; it has no sudo) | see below | `sudo npx -y playwright install-deps firefox chromium` (or via a venv: `sudo python -m playwright install-deps firefox chromium`) |
| Non-root runner user `runner` with a writable home | Playwright browsers cache in `/home/runner/.cache/ms-playwright`, Python/Node in the runner's `_work/_tool` | `id runner` | Already exists (shared with abeceda-hrou); run `config.sh` as `runner` |
| ~5 GB free disk | browsers (~1 GB), toolchains, pip cache, workspace | `df -h ~` | — |
| Outbound HTTPS | github.com, measured sites, Cloudflare API | `curl -sI https://api.github.com` | — |
| Correct clock | timestamps in results, TLS | `timedatectl` | `sudo timedatectl set-ntp true` |

Browser binaries are versioned per Playwright release (`playwright>=1.47`, unpinned). The workflow runs
`python -m playwright install firefox chromium` each time, which is a no-op if the matching version is cached
and a download after a Playwright upgrade. Only the system libraries must already be on the VM.

## 3. Register a runner for this repo

Get a registration token (valid 1 hour), on any machine with `gh`:
```bash
gh api -X POST repos/pavel-kubik/web-analyst/actions/runners/registration-token --jq .token
```
(or GitHub → Settings → Actions → Runners → New self-hosted runner).

On the VM (`vm-tools`, Oracle Cloud). Naming follows the existing runner for `abeceda-hrou`
(user `runner`, `/home/runner/actions-runner`, name `oci`):

| | abeceda-hrou | web-analyst |
|---|---|---|
| User | `runner` (no sudo) | `runner` |
| Directory | `/home/runner/actions-runner` | `/home/runner/actions-runner-web-analyst` |
| Runner name | `oci` | `oci` (names are unique per repo) |
| systemd unit | `actions.runner.pavel-kubik-abeceda-hrou.oci` | `actions.runner.pavel-kubik-web-analyst.oci` |

Set `ARCH` from step 1 and take the current version from
https://github.com/actions/runner/releases (v2.338.1 at time of writing):
```bash
sudo -iu runner                     # install and configure as the runner user
ARCH=x64          # or arm64 (Ampere instances)
VER=2.338.1
mkdir ~/actions-runner-web-analyst && cd ~/actions-runner-web-analyst
curl -fsSL -o runner.tar.gz \
  https://github.com/actions/runner/releases/download/v$VER/actions-runner-linux-$ARCH-$VER.tar.gz
tar xzf runner.tar.gz
./config.sh --url https://github.com/pavel-kubik/web-analyst --token <TOKEN> \
  --name oci --unattended           # default labels: self-hosted, Linux, X64/ARM64
exit                                # back to ubuntu (has sudo)

cd /home/runner/actions-runner-web-analyst
sudo ./svc.sh install runner && sudo ./svc.sh start
sudo ./svc.sh status
```

## 4. Verify

- GitHub → Settings → Actions → Runners: `oci` shows **Idle**.
- Push any code change → the **Test** workflow runs on the VM.
- Actions → Measure → Run workflow with an ad-hoc URL: exercises Playwright without touching trends or R2.

## Operations

- Logs: `journalctl -u actions.runner.pavel-kubik-web-analyst.oci -f`; per-job logs in `/home/runner/actions-runner-web-analyst/_diag/`.
- One runner = one job at a time. Jobs queue while the VM is busy or offline; a job queued for 24 h fails.
  There is no hosted fallback.
- Runner updates itself automatically; keep the service running.
- Remove (in the runner directory): `sudo ./svc.sh uninstall`, then as `runner`: `./config.sh remove --token <REMOVAL_TOKEN>`
  (token: `gh api -X POST repos/pavel-kubik/web-analyst/actions/runners/remove-token --jq .token`).

## Security

- Jobs on the `prod` environment expose `CLOUDFLARE_API_TOKEN` (account-wide, shared with firmometr) on this VM,
  alongside the other service's runner. Narrow the token to the R2 bucket.
- The repo is private, so only collaborators can trigger `pull_request` runs. **If the repo ever becomes public,
  move `test.yml` back to `ubuntu-latest`**: fork PRs would otherwise run arbitrary code on this persistent VM.
