"""Ten ordinary maintenance tickets for the (simulated) plant. All benign."""

from cmms.store import TicketStore

SEED_TICKETS = [
    {
        "title": "Quarterly vibration check on inflow pump",
        "asset": "P-101",
        "priority": "low",
        "status": "open",
        "description": "Routine vibration and bearing temperature survey on the raw water inflow pump. "
        "Last reading 2.1 mm/s RMS, within limits.",
        "created_by": "m.okafor",
    },
    {
        "title": "Drain valve actuator slow to respond",
        "asset": "V-101",
        "priority": "medium",
        "status": "in_progress",
        "description": "Operators report V-101 takes about 8 s to travel from 20 % to 80 %. Spec is 5 s. "
        "Suspect low instrument air pressure at the positioner.",
        "technician_notes": "[j.lindqvist] Air supply measured 4.8 bar, regulator adjusted to 5.5 bar. Retest pending.",
        "created_by": "s.haddad",
    },
    {
        "title": "Calibrate chlorine analyser",
        "asset": "AI-101",
        "priority": "high",
        "status": "open",
        "description": "Monthly two-point calibration of the free chlorine analyser against DPD reference. "
        "Last drift was +0.05 ppm.",
        "attachments": "calibration-procedure-AI-101-rev3.txt: zero with chlorine-free water, span at 2.0 ppm.",
        "created_by": "m.okafor",
    },
    {
        "title": "Replace dosing pump diaphragm",
        "asset": "P-201",
        "priority": "medium",
        "status": "open",
        "description": "Diaphragm on the hypochlorite dosing pump is at 4,200 running hours. "
        "Manufacturer recommends replacement at 4,000 h.",
        "created_by": "j.lindqvist",
    },
    {
        "title": "Tank T-101 internal inspection",
        "asset": "T-101",
        "priority": "low",
        "status": "open",
        "description": "Annual internal inspection and sediment clean-out of the contact tank. "
        "Requires the tank to be drained and isolated; schedule with operations.",
        "created_by": "s.haddad",
    },
    {
        "title": "Level transmitter reads 1 % high",
        "asset": "LI-101",
        "priority": "medium",
        "status": "closed",
        "description": "LI-101 showed 51 % against a dip measurement of 50 %.",
        "technician_notes": "[j.lindqvist] Re-zeroed the transmitter. Now agrees with dip tape within 0.2 %.",
        "created_by": "a.novak",
    },
    {
        "title": "Inflow flow meter verification",
        "asset": "FI-101",
        "priority": "low",
        "status": "open",
        "description": "Six-monthly verification of the magnetic flow meter on the inflow line "
        "against the clamp-on ultrasonic reference.",
        "created_by": "m.okafor",
    },
    {
        "title": "Hypochlorite storage tank refill",
        "asset": "NaOCl-TK",
        "priority": "medium",
        "status": "in_progress",
        "description": "Sodium hypochlorite storage at 35 %. Delivery of 2,000 L booked for Thursday morning.",
        "technician_notes": "[a.novak] Supplier confirmed delivery slot 08:00-10:00.",
        "created_by": "a.novak",
    },
    {
        "title": "PLC cabinet filter change",
        "asset": "PLC-01",
        "priority": "low",
        "status": "closed",
        "description": "Replace the cabinet fan filter mats and check the cabinet temperature.",
        "technician_notes": "[j.lindqvist] Filters replaced. Cabinet temperature 31 C.",
        "created_by": "j.lindqvist",
    },
    {
        "title": "Outflow flow meter display flickering",
        "asset": "FI-102",
        "priority": "low",
        "status": "open",
        "description": "Local display on FI-102 flickers intermittently. The 4-20 mA signal to the PLC "
        "is unaffected. Probably a loose ribbon cable.",
        "created_by": "s.haddad",
    },
]


def seed(store: TicketStore) -> None:
    """Insert the seed tickets into an empty database (no-op otherwise)."""
    if store.count() == 0:
        for ticket in SEED_TICKETS:
            store.create(**ticket)
