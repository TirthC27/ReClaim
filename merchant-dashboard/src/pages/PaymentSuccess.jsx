import { useEffect, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { fetchOrder } from "../api";

export default function PaymentSuccess() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const orderId = searchParams.get("order_id");
  const [order, setOrder] = useState(null);
  const [polling, setPolling] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!orderId) {
      setError("No order_id found in URL.");
      setPolling(false);
      return;
    }

    let intervalId;
    const poll = async () => {
      try {
        const data = await fetchOrder(orderId);
        setOrder(data);
        if (data.status === "order_created") {
          setPolling(false);
          clearInterval(intervalId);
        }
      } catch (e) {
        setError(e.message);
      }
    };

    poll();
    intervalId = setInterval(poll, 3000);

    return () => clearInterval(intervalId);
  }, [orderId]);

  const statusIcon = (s) => {
    switch (s) {
      case "order_created": return "✅";
      case "paid": return "💳";
      case "pending_payment": return "⏳";
      case "failed": return "❌";
      default: return "🔄";
    }
  };

  return (
    <div className="card" style={{ textAlign: "center" }}>
      <div className="card-header" style={{ justifyContent: "center" }}>
        <div>
          <h2>
            {order?.status === "order_created"
              ? "🎉 Order Confirmed!"
              : order?.status === "paid"
              ? "💳 Payment Received"
              : "Processing..."}
          </h2>
          <p className="subtitle">
            {order?.status === "order_created"
              ? "Your Shopify order has been created successfully."
              : polling
              ? "Waiting for order confirmation…"
              : ""}
          </p>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {polling && !order && (
        <div style={{ padding: 40 }}>
          <span className="spinner spinner-lg" />
          <p style={{ marginTop: 16, color: "var(--text-muted)" }}>
            Checking payment status…
          </p>
        </div>
      )}

      {order && (
        <div style={{ textAlign: "left", marginTop: 16 }}>
          <div className="document-list">
            <div className="document-row">
              <div className="document-info">
                <span className="file-icon" style={{ fontSize: "2rem" }}>{statusIcon(order.status)}</span>
                <div>
                  <strong>Order Status</strong>
                  <span className="document-meta">{order.status.replace(/_/g, " ").toUpperCase()}</span>
                </div>
              </div>
              <span className="badge badge-success">{order.status}</span>
            </div>

            {order.shopify_order_id && (
              <div className="document-row">
                <div className="document-info">
                  <span className="file-icon">🛍️</span>
                  <div>
                    <strong>Shopify Order</strong>
                    <span className="document-meta">#{order.shopify_order_id}</span>
                  </div>
                </div>
              </div>
            )}

            <div className="document-row">
              <div className="document-info">
                <span className="file-icon">🆔</span>
                <div>
                  <strong>Internal Order ID</strong>
                  <span className="document-meta">{order.id}</span>
                </div>
              </div>
            </div>

            {order.merchant_id && (
              <div className="document-row">
                <div className="document-info">
                  <span className="file-icon">🏪</span>
                  <div>
                    <strong>Merchant</strong>
                    <span className="document-meta">{String(order.merchant_id).slice(0, 12)}…</span>
                  </div>
                </div>
              </div>
            )}

            {order.order_creation_failed && (
              <div className="alert alert-error" style={{ marginTop: 16 }}>
                ⚠️ Shopify order creation failed — will retry automatically.
                {order.last_shopify_error && (
                  <details style={{ marginTop: 8 }}>
                    <summary>Error details</summary>
                    <pre style={{ whiteSpace: "pre-wrap" }}>{order.last_shopify_error}</pre>
                  </details>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      <button
        className="btn btn-primary"
        style={{ marginTop: 24 }}
        onClick={() => navigate("/")}
      >
        ← Back to Dashboard
      </button>
    </div>
  );
}
