# Security policy

DVAP is a **deliberately vulnerable**, fully simulated lab. Its vulnerabilities are the point, so
this policy is about one question: **can harm get out of the lab?**

## Out of scope: the intentional vulnerabilities

Do not report these; they are the challenges. Everything listed in
[docs/VULNERABILITIES.md](https://github.com/jxbani/DVAP/blob/main/docs/VULNERABILITIES.md) and
marked `# DVAP-VULN: <challenge-id>` in the code is deliberate, including:

- prompt injection through tickets, PLC string registers, work orders, tool descriptions or memory;
- missing range checks, over-privileged tools and misleading approval summaries;
- unauthenticated Modbus/TCP, OPC UA, historian API and Valkey (Redis) bus;
- command injection in `run_diagnostic`, as long as it stays inside the sandbox (C05);
- anything the agent or a participant can do to the **simulated** plant.

Also out of scope:

- Problems that need you to change the configuration yourself, such as publishing ports beyond
  `127.0.0.1`, putting services on the `edge` network, or running containers privileged. (`api`
  mode's documented route out for the agent container is a known, opt-in trade-off.)
- Gaps in SafeEnvelope that its documentation already lists
  ([what it does not protect against](https://github.com/jxbani/DVAP/blob/main/docs/SAFEENVELOPE.md#what-safeenvelope-does-not-protect-against)).
  A clean bypass of a layer that *claims* to stop something is welcome, as a regular public issue.
- Vulnerabilities in third-party images or packages that DVAP merely pins. Report those upstream;
  Dependabot and CI's Trivy scan pick up their fixes.

## In scope: lab escapes

These are real vulnerabilities. Please report them privately (below):

- **Host impact**: anything done from inside the lab (a shell in the sandbox, a compromised service,
  a crafted ticket, string, message or model output) that reads, writes or executes on the host,
  or affects other containers or processes on it.
- **Sandbox escape**: code from C05 running with more privileges, capabilities, filesystem or network
  access than [docs/LAB_SAFETY.md](https://github.com/jxbani/DVAP/blob/main/docs/LAB_SAFETY.md) says:
  as root, writable outside `/tmp`, beyond its process and memory limits, or out of the container.
- **Unintended network exposure**: with the configuration as shipped, any lab service reachable
  from outside the machine, any port bound to an address other than `127.0.0.1`, or any route from
  a vulnerable service to the internet or the host's network (outside `api` mode's agent route).
- **Real equipment**: any code path that could reach a real PLC or an industrial network outside the
  lab's Docker network.
- **Supply chain and releases**: real credentials in the repository, a malicious dependency, or a
  way to publish images, signatures, attestations or release assets that don't come from this
  repository's release workflow.
- **CTF integrity**: forging a valid flag without solving the challenge or knowing the secret.

## How to report

Use **GitHub private vulnerability reporting**: the repository's
[Security tab → Report a vulnerability](https://github.com/jxbani/DVAP/security/advisories/new).
Please include:

- the version (`./dvap version`, or the commit hash), your OS, and your Docker and Compose versions;
- the steps to reproduce, starting from `./dvap up`;
- what leaves the lab, and how far.

Do not open a public issue or pull request for an in-scope report until it is fixed.

We aim to acknowledge reports within 7 days and fix confirmed lab escapes before anything else. We
credit reporters in the advisory and the changelog, unless you'd rather not be named. Only the
latest release and `main` are supported.
