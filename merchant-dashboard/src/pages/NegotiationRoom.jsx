import { useEffect, useState, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { startBundleNegotiation, getNegotiationStreamUrl, fetchBundleNegotiationRounds } from "../api";
import "./NegotiationRoom.css";

export default function NegotiationRoom() {
  const { poolId } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState("idle");
  const [rounds, setRounds] = useState([]);
  const [buyerDecision, setBuyerDecision] = useState(null);
  const [error, setError] = useState(null);
  const eventSourceRef = useRef(null);
  const messagesEndRef = useRef(null);

  // Group events by round
  const round1 = rounds.filter(r => r.round_number === 1);
  const round2 = rounds.filter(r => r.round_number === 2);

  const startNegotiation = async () => {
    try {
      setStatus("starting");
      setError(null);
      await startBundleNegotiation(poolId);
      connectStream();
    } catch (e) {
      setError(e.message);
      setStatus("idle");
    }
  };

  const connectStream = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const url = getNegotiationStreamUrl(poolId);
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.addEventListener("negotiation_started", () => {
      setStatus("running");
    });

    es.addEventListener("offer_submitted", (e) => {
      const data = JSON.parse(e.data);
      setRounds(prev => {
        // Prevent duplicates
        if (prev.some(r => r.id === data.id)) return prev;
        return [...prev, data];
      });
    });

    es.addEventListener("buyer_decision", (e) => {
      const data = JSON.parse(e.data);
      setBuyerDecision(data);
    });

    es.addEventListener("buyer_error", (e) => {
      const data = JSON.parse(e.data);
      setError(`Buyer Agent Error: ${data.error}`);
      setStatus("error");
      es.close();
    });

    es.addEventListener("negotiation_complete", () => {
      setStatus("completed");
      es.close();
    });

    es.onerror = (err) => {
      console.error("SSE Error:", err);
      // Optional: es.close() if fatal
    };
  };

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [rounds, buyerDecision]);

  useEffect(() => {
    // Initial fetch to see if negotiation already happened
    fetchBundleNegotiationRounds(poolId).then(data => {
      if (data.rounds && data.rounds.length > 0) {
        setRounds(data.rounds);
        if (data.status === "converged") {
          setStatus("completed");
          // Fetch allocations if completed
        } else if (data.status === "in_progress") {
          connectStream();
        }
      }
    }).catch(console.error);

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [poolId]);

  const renderMerchantBubble = (offer) => {
    const isHold = offer.action === "hold";
    
    return (
      <div key={offer.id} className={`merchant-bubble fade-in`}>
        <div className="bubble-header">
          <strong>{offer.merchant_name}</strong>
          {offer.is_final && <span className="final-badge">FINAL</span>}
        </div>
        
        <div className="bubble-body">
          <p className="reasoning">"{offer.reasoning}"</p>
          
          <div className="offer-action">
            {isHold ? (
              <div className="hold-action">Held at ₹{Number(offer.total_price).toLocaleString("en-IN")}</div>
            ) : (
              <div className="price-action">
                {offer.previous_price && (
                  <span className="strike">₹{Number(offer.previous_price).toLocaleString("en-IN")}</span>
                )}
                <strong className="new-price">₹{Number(offer.total_price).toLocaleString("en-IN")}</strong>
              </div>
            )}
          </div>
        </div>
        
        {/* Debug/audit drawer (Normally hidden from other merchants, shown to platform admins) */}
        <details className="audit-drawer">
          <summary>Agent Economics Snapshot</summary>
          <pre>{JSON.stringify(offer.economics_snapshot, null, 2)}</pre>
        </details>
      </div>
    );
  };

  return (
    <div className="negotiation-room">
      <div className="room-header">
        <div className="header-titles">
          <h2>🔴 LIVE NEGOTIATION ROOM</h2>
          <p>Pool ID: <code>{String(poolId).slice(0, 8)}...</code></p>
        </div>
        
        <div className="header-actions">
          <button className="btn" onClick={() => navigate("/")}>← Back</button>
          {status === "idle" && (
            <button className="btn btn-primary generate-btn" onClick={startNegotiation}>
              ⚡ Start Negotiation
            </button>
          )}
          {status === "running" && <span className="status-badge running">Negotiating...</span>}
          {status === "completed" && <span className="status-badge complete">Negotiation Closed</span>}
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="room-content">
        <div className="chat-feed">
          {round1.length > 0 && (
            <div className="round-section">
              <div className="round-divider">
                <span>ROUND 1: Initial Offers</span>
              </div>
              <div className="bubble-grid">
                {round1.map(renderMerchantBubble)}
              </div>
            </div>
          )}

          {round2.length > 0 && (
            <div className="round-section">
              <div className="round-divider">
                <span>ROUND 2: Final Opportunity</span>
                <small>Competitor prices revealed</small>
              </div>
              <div className="bubble-grid">
                {round2.map(renderMerchantBubble)}
              </div>
            </div>
          )}

          {status === "completed" && !buyerDecision && (
            <div className="buyer-evaluating fade-in">
              <span className="spinner"></span>
              <strong>Buyer Agent is evaluating final offers...</strong>
            </div>
          )}

          {buyerDecision && (
            <div className="buyer-decision-card fade-in">
              <div className="buyer-header">🤖 BUYER AGENT DECISION</div>
              <div className="buyer-body">
                {buyerDecision.reasoning && (
                  <div className="buyer-reasoning">
                    <p><strong>Strategy:</strong> {buyerDecision.decision}</p>
                    <p><strong>Tradeoff:</strong> {buyerDecision.reasoning.tradeoff}</p>
                    <p><strong>Policy:</strong> {buyerDecision.reasoning.policy_reference}</p>
                  </div>
                )}
                {buyerDecision.allocation_plan?.map((cart, idx) => (
                  <div key={idx} className="cart-decision">
                    <h4>Cart {cart.cart_id.slice(0, 8)}...</h4>
                    {cart.assignments.map((a, i) => {
                      const merchantName = rounds.find(r => r.merchant_id === a.merchant_id)?.merchant_name || a.merchant_id.slice(0, 8);
                      return (
                        <div key={i} className="assignment-row">
                          <span>📦 Group {a.product_group_id.slice(0, 6)}</span>
                          <span>→</span>
                          <strong>{merchantName}</strong>
                          <span className="price">₹{a.line_total.toLocaleString('en-IN')}</span>
                        </div>
                      );
                    })}
                    <div className="cart-total">
                      Total: ₹{cart.total_price.toLocaleString('en-IN')}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          
          <div ref={messagesEndRef} />
        </div>

        {/* Price Ladder Sidebar */}
        <div className="ladder-sidebar">
          <h3>Price Ladder</h3>
          <div className="ladder-content">
             {/* We can aggregate the latest prices here */}
             {[...new Set(rounds.map(r => r.merchant_name))].map(merchantName => {
               const mRounds = rounds.filter(r => r.merchant_name === merchantName);
               const r1 = mRounds.find(r => r.round_number === 1);
               const r2 = mRounds.find(r => r.round_number === 2);
               
               if (!r1) return null;
               
               return (
                 <div key={merchantName} className="ladder-merchant">
                    <h4>{merchantName}</h4>
                    <div className="ladder-steps">
                      <div className="ladder-step">
                        <span className="step-label">R1</span>
                        <span className="step-price">₹{Number(r1.total_price).toLocaleString('en-IN')}</span>
                      </div>
                      {r2 && (
                        <div className="ladder-step final">
                          <span className="step-label">R2</span>
                          <span className="step-price">₹{Number(r2.total_price).toLocaleString('en-IN')}</span>
                        </div>
                      )}
                    </div>
                 </div>
               )
             })}
          </div>
        </div>
      </div>
    </div>
  );
}
