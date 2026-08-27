import { useState, useEffect } from "react";
import { fetchVendors, onboardMerchant } from "../api";

export default function SignupForm({ onComplete }) {
  const [vendors, setVendors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const [name, setName] = useState("");
  const [vendor, setVendor] = useState("");
  const [marginFloor, setMarginFloor] = useState("");

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

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const merchant = await onboardMerchant({
        name,
        shopify_vendor_name: vendor,
        margin_floor_pct: marginFloor ? parseFloat(marginFloor) : null,
      });
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
