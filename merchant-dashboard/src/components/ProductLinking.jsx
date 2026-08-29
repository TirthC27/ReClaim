import { useState, useEffect, useRef } from "react";
import {
  fetchShopifyProducts,
  linkProducts,
  fetchProductGroups,
  searchProductGroups,
  createProductGroup,
} from "../api";

function SearchableGroupSelect({ productTitle, defaultGroups, onSelectGroup }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const wrapperRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return;
    
    if (query.length < 2) {
      setResults(defaultGroups);
      return;
    }
    
    setLoading(true);
    const timer = setTimeout(() => {
      searchProductGroups(query)
        .then(setResults)
        .catch(console.error)
        .finally(() => setLoading(false));
    }, 800);
    return () => clearTimeout(timer);
  }, [query, isOpen, defaultGroups]);

  // Click outside to close
  useEffect(() => {
    function handleClickOutside(event) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSelect = (group) => {
    setQuery(group.model_name);
    onSelectGroup(group.id);
    setIsOpen(false);
  };

  const handleCreateNew = async () => {
    const sku = productTitle
      .toUpperCase()
      .replace(/[^A-Z0-9]/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "");
      
    setLoading(true);
    try {
      const newGroup = await createProductGroup({
        model_name: query,
        canonical_sku: sku,
      });
      // Force update of results so the newly created group shows up in subsequent searches
      setResults((prev) => [newGroup, ...prev]);
      handleSelect(newGroup);
    } catch (err) {
      console.error("Failed to create group:", err);
      alert("Failed to create new product group: " + err.message);
    } finally {
      setLoading(false);
    }
  };

  const exactMatch = results.some(r => r.model_name.toLowerCase() === query.toLowerCase());

  return (
    <div ref={wrapperRef} style={{ position: "relative", width: "100%" }}>
      <input
        type="text"
        placeholder="Search or type new group name..."
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setIsOpen(true);
          // clear parent selection when typing to force a new selection
          onSelectGroup(null);
        }}
        onFocus={() => setIsOpen(true)}
        className="input-field"
        style={{ width: "100%", padding: "8px", boxSizing: "border-box" }}
      />
      
      {isOpen && (
        <ul
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            background: "var(--bg-primary, white)",
            border: "1px solid var(--border, #ccc)",
            maxHeight: 200,
            overflowY: "auto",
            zIndex: 10,
            listStyle: "none",
            margin: 0,
            padding: 0,
            boxShadow: "0 4px 6px rgba(0,0,0,0.1)",
          }}
        >
          {loading && <li style={{ padding: 8, color: "var(--text-muted, #666)" }}>Loading...</li>}
          
          {results.map((g) => (
            <li
              key={g.id}
              onClick={() => handleSelect(g)}
              style={{ padding: 8, cursor: "pointer", borderBottom: "1px solid var(--border, #eee)", color: "var(--text-primary, black)" }}
            >
              {g.model_name} <span style={{color: "var(--text-muted, #888)", fontSize: "0.85em"}}>{g.canonical_sku}</span>
            </li>
          ))}
          
          {!exactMatch && query.length > 0 && (
            <li
              onClick={handleCreateNew}
              style={{
                padding: 8,
                cursor: "pointer",
                background: "var(--bg-secondary, #f0f8ff)",
                color: "var(--primary, #0066cc)",
                fontWeight: "bold",
              }}
            >
              + Create new group: "{query}"
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

export default function ProductLinking({ merchant, onComplete }) {
  const [products, setProducts] = useState([]);
  const [groups, setGroups] = useState([]);
  const [assignments, setAssignments] = useState({});
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

  const handleGroupSelect = (productId, groupId) => {
    setAssignments((prev) => {
      const newGroupId = groupId || null;
      if (prev[productId] === newGroupId) return prev;
      return { ...prev, [productId]: newGroupId };
    });
  };

  const handleSubmit = async () => {
    setError("");
    setSubmitting(true);

    const assignmentList = products.map((p) => {
      const pid = String(p.id);
      const entry = {
        shopify_product_id: pid,
        product_group_id: assignments[pid] || null,
        new_group: null, // we no longer use the inline new_group creation feature on the backend, groups are created via API immediately
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
                    <SearchableGroupSelect
                      productTitle={p.title}
                      defaultGroups={groups}
                      onSelectGroup={(id) => handleGroupSelect(pid, id)}
                    />
                  </div>
                </div>
              );
            })}
          </div>

          <button
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={submitting}
            style={{ marginTop: 16 }}
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
