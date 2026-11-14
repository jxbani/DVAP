"""Reading and writing the virtual PLC over Modbus/TCP, decoded to engineering units.

Shared by the historian (reads) and mcp-plant (reads and writes). All simulated.
"""

from pymodbus.client import AsyncModbusTcpClient

from dvap_common.plc_tags import TAGS, Tag, blocks

TAG = {t.name: t for t in TAGS}
# Modbus function code used to write each table.
WRITE = {"coil": "write_coils", "holding": "write_registers"}


async def read_all(client: AsyncModbusTcpClient) -> dict:
    """Read every tag in the register map and decode it to engineering units."""
    readers = {
        "coil": client.read_coils,
        "holding": client.read_holding_registers,
        "input": client.read_input_registers,
    }
    values: dict = {}
    for table, address, count, tags in blocks():
        r = await readers[table](address, count=count)
        if r.isError():
            raise ConnectionError(f"Modbus read {table}@{address} failed: {r}")
        raw = r.bits if table == "coil" else r.registers
        for tag in tags:
            offset = tag.address - address
            values[tag.name] = tag.decode(raw[offset : offset + tag.length])
    return values


async def write_tag(client: AsyncModbusTcpClient, name: str, value) -> None:
    """Encode and write one writable tag by name."""
    tag: Tag = TAG[name]
    if not tag.writable:
        raise ValueError(f"{name} is read-only")
    r = await getattr(client, WRITE[tag.table])(tag.address, tag.encode(value))
    if r.isError():
        raise ConnectionError(f"Modbus write to {name} failed: {r}")
