from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
import sqlite3
import math
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

DB_PATH = "bom_rules.db"

app = FastAPI()

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

# Allow your frontend (index.html) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- INPUT MODEL FROM FRONTEND ----------

class MachineInput(BaseModel):
    PLC_brand: str
    HMI_size: int
    DI: int
    DO: int
    AI: int = 0
    AO: int = 0
    servos: int = 0
    ac_drives: int = 0
    doors: int = 0
    magazines: int = 0
    supply_voltage: str | None = None
    safety_level: str | None = None


# ---------- DB HELPERS ----------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # Single table: each row is a rule + component info
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            plc_brand TEXT,
            condition_expr TEXT,
            qty_expr TEXT,

            part_no TEXT NOT NULL,
            description TEXT NOT NULL,
            manufacturer TEXT,
            category TEXT,
            unit TEXT,
            notes TEXT,

            price INTEGER   -- NEW COLUMN (in euro)
        );
        """
    )

    # Seed some Siemens-based example rules if table is empty
    cur.execute("SELECT COUNT(*) AS cnt FROM rules;")
    if cur.fetchone()["cnt"] == 0:
        rules = [
            # Siemens DI modules: 16 DI per card
            (
                "Siemens DI modules",
                "SIEMENS",
                "DI > 0",
                "math.ceil(DI / 16)",
                "6ES7-DI16",
                "Siemens DI module 16DI",
                "Siemens",
                "PLC_IO",
                "pcs",
                "S7-1200 compatible digital input module",
                250,   # €250.00
            ),
        ]

        cur.executemany(
            """
            INSERT INTO rules (
                name, plc_brand, condition_expr, qty_expr,
                part_no, description, manufacturer, category, unit, notes, price
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            rules,
        )

        print("Database initialized with sample Siemens rules.")

    conn.commit()
    conn.close()


@app.on_event("startup")
def on_startup():
    init_db()


# ---------- API: SIMPLE ROOT ----------

@app.get("/")
def root():
    return {"message": "BOM API with 1D rules DB is running"}


# ---------- API: GENERATE BOM ----------

@app.post("/generate-bom")
def generate_bom(machine: MachineInput):
    params = machine.dict()
    brand = machine.PLC_brand.strip().upper()

    conn = get_db()
    cur = conn.cursor()

    # Select rules matching this brand OR generic (plc_brand IS NULL)
    cur.execute(
        """
        SELECT *
        FROM rules
        WHERE plc_brand IS NULL OR UPPER(plc_brand) = ?
        """,
        (brand,),
    )
    rules = cur.fetchall()
    conn.close()

    bom_by_part: dict[str, dict] = {}

    safe_globals = {"math": math}
    safe_locals = params.copy()

    for r in rules:
        cond_expr = r["condition_expr"]
        qty_expr = r["qty_expr"]

        # Condition: if empty/NULL, treat as "always true"
        if cond_expr is None or cond_expr.strip() == "":
            condition_ok = True
        else:
            try:
                condition_ok = bool(eval(cond_expr, safe_globals, safe_locals))
            except Exception as e:
                print(f"Error evaluating condition for rule {r['id']}: {e}")
                continue

        if not condition_ok:
            continue

        # Quantity: if empty/NULL, default to 1
        if qty_expr is None or qty_expr.strip() == "":
            qty = 1
        else:
            try:
                qty = eval(qty_expr, safe_globals, safe_locals)
            except Exception as e:
                print(f"Error evaluating qty for rule {r['id']}: {e}")
                continue

        try:
            qty = int(qty)
        except Exception:
            continue

        if qty <= 0:
            continue

        part_no = r["part_no"]

        if part_no not in bom_by_part:
            bom_by_part[part_no] = {
                "part_no": part_no,
                "description": r["description"],
                "manufacturer": r["manufacturer"],
                "category": r["category"],
                "unit": r["unit"],
                "notes": r["notes"],
                "quantity": 0,
                "price": int((r["price"] if "price" in r.keys() else r["Price"]) or 0),
                "total_price": 0,
            }

        bom_by_part[part_no]["quantity"] += qty
        bom_by_part[part_no]["total_price"] = (
            bom_by_part[part_no]["quantity"] * bom_by_part[part_no]["price"]
        )

    return {"bom": list(bom_by_part.values())}


# ---------- ADMIN UI: RULES (ONLY) ----------

@app.get("/admin/rules", response_class=HTMLResponse)

def admin_rules():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rules ORDER BY id;")
    rules = cur.fetchall()
    conn.close()

    rules_html = ""
    for r in rules:
        rules_html += f"""
        <tr>
          <td>{r['id']}</td>
          <td>{r['name']}</td>
          <td>{r['plc_brand'] or ''}</td>
          <td>{r['condition_expr'] or ''}</td>
          <td>{r['qty_expr'] or ''}</td>
          <td>{r['part_no']}</td>
          <td>{r['description']}</td>
          <td>{r['manufacturer'] or ''}</td>
          <td>{r['category'] or ''}</td>
          <td>{r['unit'] or ''}</td>
          <td>{r['notes'] or ''}</td>
          <td>{r['price'] or ''}</td>
        </tr>
        """

    html = f"""
    <html>
    <head>
      <title>Admin - Rules</title>
      <style>
        body {{ font-family: Arial, sans-serif; padding: 20px; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
        th, td {{ border: 1px solid #ccc; padding: 6px 8px; font-size: 0.85rem; }}
        th {{ background: #f0f0f0; }}
        input, textarea {{ width: 100%; padding: 4px; }}
        .form-row {{ margin-bottom: 8px; }}
        .container {{ max-width: 1100px; margin: 0 auto; }}
        button {{ padding: 6px 10px; }}
      </style>
    </head>
    <body>
      <div class="container">
        <h1>Rules Admin (1D: rule + component in one row)</h1>

        <h3>Available Variables & Examples</h3>
        <ul>
         <li><b>PLC_brand</b> – string, e.g. <code>PLC_brand == "SIEMENS"</code></li>
         <li><b>HMI_size</b> – inches, e.g. <code>HMI_size >= 10</code></li>
         <li><b>DI</b> – digital inputs, e.g. <code>DI > 0</code></li>
         <li><b>DO</b> – digital outputs, e.g. <code>math.ceil(DO / 16)</code></li>
         <li><b>AI</b> – analog inputs, e.g. <code>AI > 0</code></li>
          <li><b>AO</b> – analog outputs, e.g. <code>AO > 0</code></li>
          <li><b>servos</b> – servo axes, e.g. <code>servos</code></li>
          <li><b>ac_drives</b> – AC drives, e.g. <code>ac_drives * 2</code></li>
        </ul>

        <p><b>Functions:</b> <code>math.ceil()</code>, <code>math.floor()</code></p>

        <p><b>Example:</b></p>
        <pre>
        Condition: DI > 0 and PLC_brand == "SIEMENS"
        Quantity:  math.ceil(DI / 16)
        </pre>


        <!--<h2>Add Rule</h2>
        <form method="post" action="/admin/rules">
          <div class="form-row">
            <label>Name</label>
            <input name="name" required>
          </div>

          <div class="form-row">
            <label>PLC Brand (e.g. Rockwell, Schneider) – leave empty for all brands</label>
            <input name="plc_brand">
          </div>

          <div class="form-row">
            <label>Condition expression (e.g. "DI > 0" or "servos > 0") – leave empty for always true</label>
            <input name="condition_expr">
          </div>

          <div class="form-row">
            <label>Quantity expression (e.g. "math.ceil(DI / 16)" or "servos") – leave empty for 1</label>
            <input name="qty_expr">
          </div>

          <hr />

          <div class="form-row">
            <label>Part No</label>
            <input name="part_no" required>
          </div>

          <div class="form-row">
            <label>Description</label>
            <input name="description" required>
          </div>

          <div class="form-row">
            <label>Manufacturer</label>
            <input name="manufacturer">
          </div>

          <div class="form-row">
            <label>Category (e.g. PLC_IO, TERMINAL, SERVO, DRIVE)</label>
            <input name="category">
          </div>

          <div class="form-row">
            <label>Unit (pcs, m, set, etc.)</label>
            <input name="unit">
          </div>

          <div class="form-row">
            <label>Notes</label>
            <textarea name="notes" rows="2"></textarea>
          </div>

          <div class="form-row">
          <label>Price (in euro, e.g. 250 = €250.00)</label>
          <input name="price" type="number">
          </div>

          <button type="submit">Add Rule</button>
        </form>-->

        <h2>Existing Rules</h2>
        <table id="rules-table">
        <thead>
            <tr>
            <th>Name</th>
            <th>Brand</th>
            <th>Condition</th>
            <th>Qty</th>
            <th>Part</th>
            <th>Description</th>
            <th>Manufacturer</th>
            <th>Category</th>
            <th>Unit</th>
            <th>Notes</th>
            <th>Price</th>
            <th>Actions</th>
            </tr>
        </thead>
        <tbody></tbody>
        </table>

        <button onclick="addRow()">Add Rule</button>

        <script>
        const API = "";

        async function loadRules() {{
            const res = await fetch("/api/rules");
            const data = await res.json();

            const tbody = document.querySelector("#rules-table tbody");
            tbody.innerHTML = "";

            data.forEach(function(rule) {{
                const row = createRow(rule);
                tbody.appendChild(row);
            }});
        }}

        function createRow(rule = {{}}) {{
            const tr = document.createElement("tr");

            tr.innerHTML = `
                <td><input value="${{rule.name || ""}}"></td>
                <td><input value="${{rule.plc_brand || ""}}"></td>
                <td><input value="${{rule.condition_expr || ""}}"></td>
                <td><input value="${{rule.qty_expr || ""}}"></td>
                <td><input value="${{rule.part_no || ""}}"></td>
                <td><input value="${{rule.description || ""}}"></td>
                <td><input value="${{rule.manufacturer || ""}}"></td>
                <td><input value="${{rule.category || ""}}"></td>
                <td><input value="${{rule.unit || ""}}"></td>
                <td><input value="${{rule.notes || ""}}"></td>
                <td><input type="number" value="${{rule.price || rule.Price || 0}}"></td>
                <td>
                    <button onclick="saveRow(this, ${{rule.id || 'null'}})">💾</button>
                    <button onclick="deleteRow(this, ${{rule.id || 'null'}})">❌</button>
                </td>
            `;

            return tr;
        }}

        async function saveRow(btn, id) {{
            const row = btn.closest("tr");
            const inputs = row.querySelectorAll("input");

            const data = {{
                name: inputs[0].value,
                plc_brand: inputs[1].value,
                condition_expr: inputs[2].value,
                qty_expr: inputs[3].value,
                part_no: inputs[4].value,
                description: inputs[5].value,
                manufacturer: inputs[6].value,
                category: inputs[7].value,
                unit: inputs[8].value,
                notes: inputs[9].value,
                price: Number(inputs[10].value)
            }};

            if (id) {{
                await fetch(`/api/rules/${{id}}`, {{
                    method: "PUT",
                    headers: {{"Content-Type": "application/json"}},
                    body: JSON.stringify(data)
                }});
            }} else {{
                await fetch(`/api/rules`, {{
                    method: "POST",
                    headers: {{"Content-Type": "application/json"}},
                    body: JSON.stringify(data)
                }});
            }}

            loadRules();
        }}

        async function deleteRow(btn, id) {{
            if (!id) {{
                btn.closest("tr").remove();
                return;
            }}

            await fetch(`/api/rules/${{id}}`, {{ method: "DELETE" }});
            loadRules();
        }}

        function addRow() {{
            const tbody = document.querySelector("#rules-table tbody");
            tbody.appendChild(createRow());
        }}

        loadRules();
        </script>
      </div>
    </body>
    </html>
    """
    return html


@app.post("/admin/rules")
def admin_add_rule(
    name: str = Form(...),
    plc_brand: str = Form(""),
    condition_expr: str = Form(""),
    qty_expr: str = Form(""),
    part_no: str = Form(...),
    description: str = Form(...),
    manufacturer: str = Form(""),
    category: str = Form(""),
    unit: str = Form(""),
    notes: str = Form(""),
    price: int = Form(0),
):
    plc_brand_val = plc_brand.strip().upper() or None
    cond_val = condition_expr.strip() or None
    qty_val = qty_expr.strip() or None

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO rules (
            name, plc_brand, condition_expr, qty_expr,
            part_no, description, manufacturer, category, unit, notes, price
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            name,
            plc_brand_val,
            cond_val,
            qty_val,
            part_no,
            description,
            manufacturer or None,
            category or None,
            unit or None,
            notes or None,
            price,
        ),
    )
    conn.commit()
    conn.close()

    return RedirectResponse(url="/admin/rules", status_code=303)

@app.get("/api/rules")
def get_rules():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rules")
    rows = cur.fetchall()
    conn.close()

    result = []
    for r in rows:
        row = dict(r)

        # Handle old DBs where column might be "Price"
        if "Price" in row and "price" not in row:
            row["price"] = int(row["Price"] or 0)
        else:
            row["price"] = int(row.get("price") or 0)

        result.append(row)

    return result

@app.put("/api/rules/{rule_id}")
def update_rule(rule_id: int, data: dict):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE rules SET
            name=?,
            plc_brand=?,
            condition_expr=?,
            qty_expr=?,
            part_no=?,
            description=?,
            manufacturer=?,
            category=?,
            unit=?,
            notes=?,
            price=?
        WHERE id=?
    """, (
        data.get("name"),
        data.get("plc_brand"),
        data.get("condition_expr"),
        data.get("qty_expr"),
        data.get("part_no"),
        data.get("description"),
        data.get("manufacturer"),
        data.get("category"),
        data.get("unit"),
        data.get("notes"),
        data.get("price"),
        rule_id
    ))

    conn.commit()
    conn.close()

    return {"status": "ok"}

@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM rules WHERE id=?", (rule_id,))
    conn.commit()
    conn.close()

    return {"status": "deleted"}

@app.post("/api/rules")
def create_rule(data: dict):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO rules (
            name, plc_brand, condition_expr, qty_expr,
            part_no, description, manufacturer, category, unit, notes, price
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("name"),
        data.get("plc_brand"),
        data.get("condition_expr"),
        data.get("qty_expr"),
        data.get("part_no"),
        data.get("description"),
        data.get("manufacturer"),
        data.get("category"),
        data.get("unit"),
        data.get("notes"),
        data.get("price", 0),
    ))

    conn.commit()
    conn.close()

    return {"status": "created"}
