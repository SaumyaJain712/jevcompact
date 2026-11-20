"""Generate a Mermaid ER diagram (docs/diagrams/er.mmd) from server/db/schema.sql."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "server" / "db" / "schema.sql"
OUT = ROOT / "docs" / "diagrams" / "er.mmd"

TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", re.S)
COL_RE = re.compile(r'^\s*"?(\w+)"?\s+(TEXT|INTEGER|REAL)\b(.*)$')


def main() -> None:
    sql = re.sub(r"--[^\n]*", "", SCHEMA.read_text())
    lines, rels = ["erDiagram"], []
    for table, body in TABLE_RE.findall(sql):
        lines.append(f"    {table} {{")
        pk_cols = set()
        m = re.search(r"PRIMARY KEY \(([^)]*)\)", body)
        if m:
            pk_cols = {c.strip().strip('"') for c in m.group(1).split(",")}
        for raw in body.split("\n"):
            cm = COL_RE.match(raw)
            if not cm:
                continue
            col, typ, rest = cm.groups()
            keys = []
            if "PRIMARY KEY" in rest or col in pk_cols:
                keys.append("PK")
            ref = re.search(r"REFERENCES (\w+)\((\w+)\)", rest)
            if ref:
                keys.append("FK")
                rels.append(f'    {ref.group(1)} ||--o{{ {table} : "{col}"')
            lines.append(f"        {typ.lower()} {col}{' ' + ','.join(keys) if keys else ''}")
        lines.append("    }")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines + sorted(set(rels))) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
