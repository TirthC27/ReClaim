import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { fetchAllocations } from "../api";

export default function AllocationView() {
  const { poolId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchAllocations(poolId)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [poolId]);

  return (
    <div className="card">
      <div className="card-header">
        <div className="step-badge">⚖️</div>
        <div>
          <h2>9A.2 Allocation Transparency</h2>
          <p className="subtitle">
            Round-robin fairness results for pool{" "}
            <code>{String(poolId).slice(0, 8)}…</code>
          </p>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {loading ? (
        <div className="skeleton-list">
          {[1, 2, 3].map((i) => (
            <div key={i} className="skeleton" style={{ height: 56 }} />
          ))}
        </div>
      ) : !data ? (
        <div className="empty-state"><p>No allocation data found.</p></div>
      ) : (
        <>
          {data.rotation_order && (
            <div style={{ marginBottom: 20, fontSize: "0.9rem", color: "var(--text-secondary)" }}>
              <strong>Rotation order:</strong>{" "}
              {data.rotation_order.map((m, i) => (
                <span key={m}>
                  {i > 0 && " → "}
                  <code>{String(m).slice(0, 8)}…</code>
                </span>
              ))}
            </div>
          )}

          <div className="document-list">
            <h3>{data.total_allocations} Allocations</h3>
            {(data.allocations || []).map((a) => (
              <div key={a.id} className="document-row">
                <div className="document-info">
                  <span className="file-icon">📋</span>
                  <div>
                    <strong>
                      Signal {String(a.demand_signal_id).slice(0, 8)}…
                    </strong>
                    <span className="document-meta">
                      → Merchant: {a.merchants?.name || String(a.merchant_id).slice(0, 8)}…
                      {" "}| Position: #{a.rotation_position}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <button
        className="btn"
        style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)", border: "1px solid var(--border)", marginTop: 16 }}
        onClick={() => navigate(`/pools/${poolId}/competition`)}
      >
        ← Back
      </button>
    </div>
  );
}
