# Beta testing DVAP

Thank you for testing! The beta runs for **two weeks**. We want to know whether a newcomer can
install DVAP from a release, without help, and whether the challenges teach what they should.
Your rough edges are the data: please note what confused you, even if you worked it out.

**Time:** about **2 to 3 hours** in total, and it doesn't have to be in one sitting.

| Step | What | Expect |
|---|---|---|
| 1 | Install from the release zip | 15 min (the first image download is most of it) |
| 2 | `./dvap doctor` | 1 min |
| 3 | Solve C01 | 15–30 min |
| 4 | Solve C02 | 10–20 min |
| 5 | Solve one hard challenge | 30–60 min |
| 6 | Try a defended variant | 10–15 min |
| 7 | `./dvap demo` | 5 min |
| 8 | [Report](#reporting) | 10 min |

!!! danger "Deliberately vulnerable"
    DVAP is insecure on purpose and fully simulated. Run it on a machine you control, keep its
    ports on `127.0.0.1`, and never connect it to real industrial equipment.

## 1. Install from the release zip

Please test the way a new user would: on a **clean machine** (or a fresh VM or user account) and
from the **release zip**, not a git clone. Time it, from the download to `./dvap up` finishing.

1. Install Docker for your OS: see [Installation](installation.md). Note anything that differs.
2. Download `dvap-<version>.zip` from the release you were invited to test on the
   [releases page](https://github.com/jxbani/DVAP/releases) (a beta is marked *Pre-release*).
3. Unzip it, open a terminal in the folder, and start the lab:
   ```bash
   ./dvap up
   ```
   On Windows without WSL, use `.\dvap.ps1 up`. The first run asks for an LLM mode:

    - **`replay`** (no model; 4 GB for Docker) is the quickest and works on any laptop;
    - **`ollama`** (a local 7B model; 8 GB for Docker) or **`api`** (your own API key) give a real
      model, which you need for most hard challenges.

    [Requirements](requirements.md) has the details. You can switch any time:
    `./dvap up --mode ollama`.

**Write down** your OS and CPU (Intel/AMD or ARM/Apple Silicon), `docker version`, the mode you
picked, the install time, and anything that went wrong (and what fixed it).

## 2. `./dvap doctor`

```bash
./dvap doctor
```

Copy its whole output into your report, even if everything passes. If something FAILs, try the
`fix:` it prints and tell us whether it worked. [Troubleshooting](troubleshooting.md) covers the
common cases.

## 3–4. Solve C01 and C02

Open the scoreboard at http://127.0.0.1:8090, start **C01**, read its story and objective, and
attack the plant through the ticket form (http://127.0.0.1:8081). The HMI
(http://127.0.0.1:8080) shows what the agent does and the **PHYSICAL INCIDENT** banner when you
succeed. Then do the same for **C02**.

Use the hints when you are stuck: they are part of what we are testing. Please only open a
challenge's solution page once you have solved it, or given up (and say which in your report).

## 5. One hard challenge

Pick any challenge marked *hard* on the [challenge list](challenges/index.md): C03, C04, C05,
C06, C08, C09 or C10.

!!! note "Hard challenges and `replay` mode"
    The `replay` agent only reacts to a few textbook phrasings, so a hard challenge may simply
    not trigger in that mode, however right your idea is. If you can, switch to `ollama` or
    `api` for this step (`./dvap up --mode ollama`). If you stay on `replay`, tell us what you
    tried: knowing where it falls short is useful too.

## 6. A defended variant

Go back to a challenge you solved, start it again from the scoreboard, then turn the guard on:

```bash
./dvap defend
```

Repeat your attack. The HMI's **SafeEnvelope** panel shows each decision (allow, deny or review)
with its reason. Does the guard stop you? Does its reason make sense? Can you get around it?
(`./dvap defend --off` turns it off again; starting a challenge also resets it.)
[SafeEnvelope](SAFEENVELOPE.md) lists what it deliberately does *not* stop.

## 7. `./dvap demo`

```bash
./dvap demo
```

This is the four-minute talk demo: an attack causes a physical incident, then the same attack is
blocked by SafeEnvelope. Press Enter to advance each step, with the HMI open at
http://127.0.0.1:8080/?presenter=1. Was it clear what happened at each step?

When you are done, `./dvap down` stops the lab. Your progress is kept.

## Reporting

File **one beta feedback issue** when you finish (or stop):
**[New beta feedback](https://github.com/jxbani/DVAP/issues/new?template=beta_feedback.yml)**.
The form asks for everything above; a partial report is much better than none.

- **Something broke and blocked you?** You can also open a
  [bug report](https://github.com/jxbani/DVAP/issues/new?template=bug_report.yml) straight away,
  so we can fix it while the beta is running.
- **Questions or ideas?** Use [Discussions](https://github.com/jxbani/DVAP/discussions).
- **Found a way out of the lab** (reaching your host, your network or the internet from inside
  it)? That is a real vulnerability: report it **privately**, as [SECURITY.md](security.md)
  explains, not in a public issue.

Issues are public: don't paste API keys, tokens, or anything personal. `./dvap doctor` output
contains none of these.
