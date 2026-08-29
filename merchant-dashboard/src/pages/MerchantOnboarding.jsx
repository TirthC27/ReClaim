import { useState } from "react";
import SignupForm from "../components/SignupForm";
import ProductLinking from "../components/ProductLinking";
import DocumentUpload from "../components/DocumentUpload";

const STEPS = [
  { id: "signup", label: "Signup" },
  { id: "link", label: "Link Products" },
  { id: "documents", label: "Documents" },
];

export default function MerchantOnboarding() {
  const [step, setStep] = useState("signup");
  const [merchant, setMerchant] = useState(null);

  const handleSignupComplete = (merchantData) => {
    setMerchant(merchantData);
    setStep("link");
  };

  const handleLinkComplete = () => {
    setStep("documents");
  };

  const currentIdx = STEPS.findIndex((s) => s.id === step);

  return (
    <>
      {/* ── Progress ───────────────────────────────────────── */}
      <nav className="progress-bar">
        {STEPS.map((s, i) => (
          <button
            key={s.id}
            className={`progress-step ${
              i < currentIdx
                ? "step-done"
                : i === currentIdx
                ? "step-active"
                : "step-upcoming"
            }`}
            onClick={() => {
              if (i < currentIdx) setStep(s.id);
              if (s.id === "documents" && merchant) setStep(s.id);
            }}
            disabled={i > currentIdx && !(s.id === "documents" && merchant)}
          >
            <span className="progress-dot">
              {i < currentIdx ? "✓" : i + 1}
            </span>
            <span className="progress-label">{s.label}</span>
          </button>
        ))}
      </nav>

      {step === "signup" && (
        <SignupForm onComplete={handleSignupComplete} />
      )}

      {step === "link" && merchant && (
        <ProductLinking
          merchant={merchant}
          onComplete={handleLinkComplete}
        />
      )}

      {step === "documents" && merchant && (
        <DocumentUpload merchant={merchant} />
      )}

      {/* Merchant context badge */}
      {merchant && (
        <div className="merchant-badge">
          <span className="badge badge-info">
            🏪 {merchant.name} — {merchant.shopify_vendor_name}
          </span>
          <code className="merchant-id">{merchant.id}</code>
        </div>
      )}
    </>
  );
}
