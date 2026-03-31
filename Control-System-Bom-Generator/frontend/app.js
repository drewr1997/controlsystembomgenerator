const form = document.getElementById("machine-form");
const tbody = document.querySelector("#bom-table tbody");
const noResults = document.getElementById("no-results");

// Change this if your backend is on a different machine / port
const API_BASE = "http://127.0.0.1:8000";

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  const formData = new FormData(form);
  const payload = Object.fromEntries(formData.entries());

  // Convert numeric fields to numbers
  ["HMI_size", "DI", "DO", "AI", "AO", "servos", "ac_drives", "doors"].forEach((key) => {
    payload[key] = Number(payload[key] || 0);
  });

  try {
    const res = await fetch(`${API_BASE}/generate-bom`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      throw new Error(`Server error: ${res.status}`);
    }

    const data = await res.json();
    renderBOM(data.bom || []);
  } catch (err) {
    console.error(err);
    alert("Error calling backend. Is FastAPI running?");
  }
});

function renderBOM(bom) {
  let grandTotal = 0;
  tbody.innerHTML = "";

  if (!bom.length) {
    noResults.classList.remove("hidden");
    return;
  }

  noResults.classList.add("hidden");

  bom.forEach((item) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${item.part_no}</td>
      <td>${item.description}</td>
      <td>${item.manufacturer || ""}</td>
      <td>${item.category || ""}</td>
      <td>${item.quantity}</td>
      <td>${item.unit || ""}</td>
      <td>${item.notes || ""}</td>
      <td>€${item.price}</td>
      <td>€${item.total_price}</td>
    `;
    tbody.appendChild(tr);
    const totalPrice = Number(item.total_price || 0);
    grandTotal += totalPrice;
  });

  const totalRow = document.createElement("tr");

  totalRow.innerHTML = `
    <td colspan="7" style="text-align:right; font-weight:bold;">
      TOTAL
    </td>
    <td style="font-weight:bold;">
      €${grandTotal}
    </td>
  `;

  tbody.appendChild(totalRow);
}
