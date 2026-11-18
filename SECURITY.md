# Security policy

DVAP is **intentionally vulnerable**. Please read this before reporting.

## Not vulnerabilities

Everything listed in [docs/VULNERABILITIES.md](docs/VULNERABILITIES.md) is deliberate: prompt
injection through tickets and PLC strings, missing range checks, unauthenticated Modbus/OPC UA,
the unauthenticated Redis bus and historian, command injection in `run_diagnostic`, memory
poisoning, misleading approvals, the scheduler, and so on. So is anything that requires you to
publish the lab's ports beyond `127.0.0.1` yourself. Gaps in SafeEnvelope that are documented in
[docs/SAFEENVELOPE.md](docs/SAFEENVELOPE.md) and the README are known, too — though a clean bypass
of a layer that *claims* to stop something is welcome as a regular issue.

## Real vulnerabilities

We want to hear about anything that lets harm leave the lab, for example:

- **Lab escape**: reaching the host, the host's network or the internet from inside the lab, e.g.
  from a shell in the diagnostic sandbox (C05).
- **Exposure**: a configuration in this repository that publishes a port on anything other than
  `127.0.0.1`, or a service reachable from outside the machine.
- **Weakened containment**: the sandbox running with more privileges, capabilities or network
  access than [docs/LAB_SAFETY.md](docs/LAB_SAFETY.md) says.
- **Real equipment**: any code path that could talk to a real PLC or an industrial network
  outside the lab's Docker network.
- **Secrets or supply chain**: real credentials committed to the repo, or a malicious or
  compromised dependency.
- **CTF integrity**: forging a valid flag without solving the challenge or knowing the secret.

## How to report

Report privately through GitHub: the repository's **Security** tab → **Report a vulnerability**.
Please include the version (commit hash), your OS and Docker version, and the steps to reproduce.
Do not open a public issue for these.

We aim to acknowledge reports within 7 days and to fix confirmed lab escapes before anything else.
Only the latest `main` is supported.
