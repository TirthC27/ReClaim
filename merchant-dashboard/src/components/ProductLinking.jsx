import { useState, useEffect } from "react";
import {
  fetchShopifyProducts,
  linkProducts,
  fetchProductGroups,
} from "../api";

export default function ProductLinking({ merchant, onComplete }) {
  const [products, setProducts] = useState([]);
  const [groups, setGroups] = useState([]);
  const [assignments, setAssignments] = useState({});
  const [newGroups, setNewGroups] = useState({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  useEffect(() => {
    Promise.all([
      fetchShopifyProducts(merchant.id),
      fetchProductGroups(),
    ])
      .then(([prodData, groupData]) => {
        setProducts(prodData.products || []);
        setGroups(groupData || []);
        setLoading(false);
      })
      .catch((err) => {
        setError(`Failed to load data: ${err.message}`);
        setLoading(false);
      });
  }, [merchant.id]);

  const handleGroupChange = (productId, value) => {
    if (value === "__new__") {
      setAssignments((prev) => ({ ...prev, [productId]: null }));
      setNewGroups((prev) => ({
        ...prev,
        [productId]: { canonical_sku: "", model_name: "" },
      }));
    } else {
      setAssignments((prev) => ({ ...prev, [productId]: value || null }));
      setNewGroups((prev) => {
        const copy = { ...prev };
        delete copy[productId];
        return copy;
      });
    }
  };

  const handleNewGroupField = (productId, field, value) => {
    setNewGroups((prev) => ({
      ...prev,
      [productId]: { ...prev[productId], [field]: value },
    }));
  };

  const handleSubmit = async () => {
    setError("");
    setSubmitting(true);

    const assignmentList = products.map((p) => {
      const pid = String(p.id);
      const entry = {
        shopify_product_id: pid,
        product_group_id: assignments[pid] || null,
        new_group: newGroups[pid] || null,
      };
      return entry;
    });

    try {
      const res = await linkProducts(merchant.id, assignmentList);
      setResult(res);
      onComplete(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="card">
        <div className="card-header">
          <div className="step-badge">2</div>
          <h2>Loading products…</h2>
        </div>
        <div className="skeleton-list">
          {[1, 2, 3].map((i) => (
            <div key={i} className="skeleton" style={{ height: 72 }} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-header">
        <div className="step-badge">2</div>
        <div>
          <h2>Link Products</h2>
          <p className="subtitle">
            Assign each of your Shopify listings to a canonical product group
          </p>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {result && (
        <div className="alert alert-success">
          ✓ Linked {result.linked?.length || 0} products
          {result.errors?.length > 0 &&
            ` (${result.errors.length} errors)`}
        </div>
      )}

      {products.length === 0 ? (
        <div className="empty-state">
          <p>No Shopify products found for vendor "{merchant.shopify_vendor_name}"</p>
        </div>
      ) : (
        <>
          <div className="product-list">
            {products.map((p) => {
              const pid = String(p.id);
              return (
                <div key={pid} className="product-row">
                  <div className="product-info">
                    {p.images?.[0]?.src && (
                      <img
                        src={p.images[0].src}
                        alt={p.title}
                        className="product-thumb"
                      />
                    )}
                    <div>
                      <strong>{p.title}</strong>
                      <span className="product-meta">
                        {p.variants?.[0]?.sku && `SKU: ${p.variants[0].sku}`}
                        {p.variants?.[0]?.price &&
                          ` • ₹${p.variants[0].price}`}
                      </span>
                    </div>
                  </div>

                  <div className="product-group-select">
                    <select
                      value={
                        newGroups[pid]
                          ? "__new__"
                          : assignments[pid] || ""
                      }
                      onChange={(e) =>
                        handleGroupChange(pid, e.target.value)
                      }
                    >
                      <option value="">— Select group —</option>
                      {groups.map((g) => (
                        <option key={g.id} value={g.id}>
                          {g.model_name}
                          {g.canonical_sku && ` (${g.canonical_sku})`}
                        </option>
                      ))}
                      <option value="__new__">+ Create new group</option>
                    </select>

                    {newGroups[pid] && (
                      <div className="new-group-fields">
                        <input
                          type="text"
                          placeholder="Model name (e.g. Dell XPS 15 2024)"
                          value={newGroups[pid].model_name}
                          onChange={(e) =>
                            handleNewGroupField(
                              pid,
                              "model_name",
                              e.target.value
                            )
                          }
                          required
                        />
                        <input
                          type="text"
                          placeholder="Canonical SKU (optional)"
                          value={newGroups[pid].canonical_sku}
                          onChange={(e) =>
                            handleNewGroupField(
                              pid,
                              "canonical_sku",
                              e.target.value
                            )
                          }
                        />
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          <button
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={submitting}
          >
            {submitting ? (
              <>
                <span className="spinner" /> Linking…
              </>
            ) : (
              `Link ${products.length} Products`
            )}
          </button>
        </>
      )}
    </div>
  );
}
