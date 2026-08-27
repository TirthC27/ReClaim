import { useState, useEffect, useRef } from "react";
import { uploadDocument, fetchDocuments } from "../api";

export default function DocumentUpload({ merchant }) {
  const [documents, setDocuments] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");
  const fileInputRef = useRef(null);

  const loadDocuments = () => {
    fetchDocuments(merchant.id)
      .then((data) => setDocuments(data.documents || []))
      .catch((err) => setError(`Failed to load documents: ${err.message}`));
  };

  useEffect(() => {
    loadDocuments();
  }, [merchant.id]);

  const handleUpload = async (files) => {
    setError("");
    setSuccessMsg("");
    setUploading(true);

    for (const file of files) {
      try {
        await uploadDocument(merchant.id, file);
        setSuccessMsg((prev) =>
          prev ? `${prev}, ${file.name}` : `Uploaded: ${file.name}`
        );
      } catch (err) {
        setError((prev) =>
          prev
            ? `${prev}\n${file.name}: ${err.message}`
            : `${file.name}: ${err.message}`
        );
      }
    }

    setUploading(false);
    loadDocuments();
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragActive(false);
    if (e.dataTransfer.files?.length) {
      handleUpload(Array.from(e.dataTransfer.files));
    }
  };

  const handleDrag = (e) => {
    e.preventDefault();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleFileSelect = (e) => {
    if (e.target.files?.length) {
      handleUpload(Array.from(e.target.files));
    }
  };

  const getStatusBadge = (doc) => {
    if (doc.extracted_text) {
      return <span className="badge badge-success">Parsed</span>;
    }
    return <span className="badge badge-warning">No text</span>;
  };

  const getFileIcon = (fileName) => {
    const ext = fileName?.split(".").pop()?.toLowerCase();
    switch (ext) {
      case "pdf":
        return "📄";
      case "docx":
      case "doc":
        return "📝";
      case "txt":
        return "📃";
      default:
        return "📎";
    }
  };

  return (
    <div className="card">
      <div className="card-header">
        <div className="step-badge">3</div>
        <div>
          <h2>Upload Documents</h2>
          <p className="subtitle">
            Upload quotations, price lists, or product catalogs (PDF, DOCX, TXT)
          </p>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {successMsg && <div className="alert alert-success">✓ {successMsg}</div>}

      {/* Drop zone */}
      <div
        className={`dropzone ${dragActive ? "dropzone-active" : ""}`}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.doc,.txt,.csv,.md"
          onChange={handleFileSelect}
          style={{ display: "none" }}
        />
        {uploading ? (
          <div className="dropzone-content">
            <span className="spinner spinner-lg" />
            <p>Uploading & processing…</p>
          </div>
        ) : (
          <div className="dropzone-content">
            <span className="dropzone-icon">📁</span>
            <p>
              <strong>Drop files here</strong> or click to browse
            </p>
            <span className="hint">PDF, DOCX, TXT up to 10MB</span>
          </div>
        )}
      </div>

      {/* Document list */}
      {documents.length > 0 && (
        <div className="document-list">
          <h3>Uploaded Documents ({documents.length})</h3>
          {documents.map((doc) => (
            <div key={doc.id} className="document-row">
              <div className="document-info">
                <span className="file-icon">{getFileIcon(doc.file_name)}</span>
                <div>
                  <strong>{doc.file_name}</strong>
                  <span className="document-meta">
                    {doc.uploaded_at &&
                      new Date(doc.uploaded_at).toLocaleDateString("en-IN", {
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                  </span>
                </div>
              </div>
              <div className="document-status">
                {getStatusBadge(doc)}
                {doc.extracted_text && (
                  <span className="text-preview" title={doc.extracted_text}>
                    {doc.extracted_text.substring(0, 80)}…
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
