import { useState, useEffect } from "react";
import { fetchVendors, onboardMerchant } from "../api";

export default function SignupForm({ onComplete }) {
  const [vendors, setVendors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [showInventory, setShowInventory] = useState(false);

  const [name, setName] = useState("");
  const [vendor, setVendor] = useState("");
  const [marginFloor, setMarginFloor] = useState("");

  // Optional inventory fields (JSON strings)
  const [stockData, setStockData] = useState("");
  const [accessoryInventory, setAccessoryInventory] = useState("");
  const [warrantyCostData, setWarrantyCostData] = useState("");

  useEffect(() => {
    fetchVendors()
      .then((data) => {
        setVendors(data.vendors || []);
        setLoading(false);
      })
      .catch((err) => {
        setError(`Failed to load vendors: ${err.message}`);
        setLoading(false);
      });
  }, []);

  const tryParseJSON = (str) => {
    if (!str.trim()) return null;
    try {
      return JSON.parse(str);
    } catch {
      return undefined; // indicates parse error
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    // Validate JSON fields if provided
    if (stockData.trim()) {
      const parsed = tryParseJSON(stockData);
      if (parsed === undefined) {
        setError("Stock Data is not valid JSON.");
        return;
      }
    }
    if (accessoryInventory.trim()) {
      const parsed = tryParseJSON(accessoryInventory);
      if (parsed === undefined) {
        setError("Accessory Inventory is not valid JSON.");
        return;
      }
    }
    if (warrantyCostData.trim()) {
      const parsed = tryParseJSON(warrantyCostData);
      if (parsed === undefined) {
        setError("Warranty Cost Data is not valid JSON.");
        return;
      }
    }

    setSubmitting(true);
    try {
      const payload = {
        name,
        shopify_vendor_name: vendor,
        margin_floor_pct: marginFloor ? parseFloat(marginFloor) : null,
      };

      // Only include inventory fields if provided
      if (stockData.trim()) payload.stock_data = JSON.parse(stockData);
      if (accessoryInventory.trim()) payload.accessory_inventory = JSON.parse(accessoryInventory);
      if (warrantyCostData.trim()) payload.warranty_cost_data = JSON.parse(warrantyCostData);

      const merchant = await onboardMerchant(payload);
      onComplete(merchant);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="card">
      <div className="card-header">
        <div className="step-badge">1</div>
        <div>
          <h2>Merchant Signup</h2>
          <p className="subtitle">Register your vendor account to get started</p>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="merchant-name">Business Name</label>
          <input
            id="merchant-name"
            type="text"
            placeholder="e.g. Acme Electronics"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="vendor-select">Shopify Vendor</label>
          {loading ? (
            <div className="skeleton" style={{ height: 44 }} />
          ) : (
            <select
              id="vendor-select"
              value={vendor}
              onChange={(e) => setVendor(e.target.value)}
              required
            >
              <option value="">Select your Shopify vendor…</option>
              {vendors.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="form-group">
          <label htmlFor="margin-floor">Margin Floor (%)</label>
          <input
            id="margin-floor"
            type="number"
            step="0.01"
            min="0"
            max="100"
            placeholder="e.g. 15.00"
            value={marginFloor}
            onChange={(e) => setMarginFloor(e.target.value)}
          />
          <span className="hint">
            Minimum margin percentage to protect in offer generation
          </span>
        </div>

        {/* ── Optional Inventory Section ──────────────── */}
        <div className="form-group" style={{ marginTop: 8 }}>
          <button
            type="button"
            className="btn"
            style={{
              background: "transparent",
              border: "1px solid var(--border, #444)",
              color: "var(--text-secondary, #aaa)",
              fontSize: "0.85rem",
              padding: "6px 12px",
              cursor: "pointer",
            }}
            onClick={() => setShowInventory(!showInventory)}
          >
            {showInventory ? "▾ Hide" : "▸ Show"} Inventory &amp; Pricing
            (Optional)
          </button>
          <span className="hint" style={{ display: "block", marginTop: 4 }}>
            Providing inventory data enables richer, differentiated AI offers.
            You can also update this later via the Merchant Settings.
          </span>
        </div>

        {showInventory && (
          <>
            <div className="form-group">
              <label htmlFor="stock-data">Stock Data (JSON)</label>
              <textarea
                id="stock-data"
                rows={3}
                placeholder='{"available_qty": 25, "restock_lead_days": 7}'
                value={stockData}
                onChange={(e) => setStockData(e.target.value)}
                style={{ fontFamily: "monospace", fontSize: "0.85rem" }}
              />
            </div>

            <div className="form-group">
              <label htmlFor="accessory-inventory">
                Accessory Inventory (JSON)
              </label>
              <textarea
                id="accessory-inventory"
                rows={3}
                placeholder='{"wireless_mouse": 15, "laptop_bag": 10}'
                value={accessoryInventory}
                onChange={(e) => setAccessoryInventory(e.target.value)}
                style={{ fontFamily: "monospace", fontSize: "0.85rem" }}
              />
            </div>

            <div className="form-group">
              <label htmlFor="warranty-cost-data">
                Warranty Cost Data (JSON)
              </label>
              <textarea
                id="warranty-cost-data"
                rows={3}
                placeholder='{"1yr_extended_cost_inr": 499, "2yr_extended_cost_inr": 899}'
                value={warrantyCostData}
                onChange={(e) => setWarrantyCostData(e.target.value)}
                style={{ fontFamily: "monospace", fontSize: "0.85rem" }}
              />
            </div>
          </>
        )}

        <button
          type="submit"
          className="btn btn-primary"
          disabled={submitting || !name || !vendor}
        >
          {submitting ? (
            <>
              <span className="spinner" /> Registering…
            </>
          ) : (
            "Register Merchant"
          )}
        </button>
      </form>
    </div>
  );
}
