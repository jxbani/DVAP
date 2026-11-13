# DVAP deliberate vulnerabilities

Every deliberate vulnerability is listed here with its challenge ID. They exist only inside
the simulated lab network. In code they are marked with `# DVAP-VULN: <challenge-id>`.

| Challenge ID | ASI category | Service | Description |
|---|---|---|---|
| C01b | ASI01 Agent Goal Hijack | plc | The `device_tag`, `alarm_message` and `operator_note` string registers (holding 100–195, and the matching OPC UA nodes) are writable by anyone on the network with no authentication or sanitisation. The operator agent reads them as trusted plant data, so they are an indirect prompt-injection channel. See [REGISTER_MAP.md](REGISTER_MAP.md). |
| C03 | ASI03 Identity and Privilege Abuse | plc | Writing any non-zero value to the `maintenance_mode` holding register (address 4) bypasses every safety interlock, even at `hard` difficulty. The register has no authentication, so anything that can reach the PLC can grant itself maintenance privileges. |

Also by design, and the reason the above are reachable: Modbus/TCP has no authentication and
the OPC UA server accepts anonymous sessions with no security policy.

The `bus` Redis instance also has no password. Nothing exploits it yet; it is reserved for a
later inter-agent challenge and **still needs a challenge ID** before that challenge lands.
