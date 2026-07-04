import { useEffect, useState } from "react";

const BASE_URL = import.meta.env.VITE_API_URL || "";

function EmbeddingMap() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [count, setCount] = useState(0);
  const [wizUrl, setWizUrl] = useState("");

  useEffect(() => {
    let isMounted = true;

    const buildMap = async () => {
      try {
        const res = await fetch(`${BASE_URL}/api/embedding-map`);
        if (!res.ok) throw new Error(`API returned ${res.status}`);
        const data = await res.json();

        if (!isMounted) return;

        if (!data.count) {
          setError("No cluster embeddings found. Ingest some logs first.");
          setLoading(false);
          return;
        }

        setCount(data.count);

        // Same-origin URLs so the WizMap iframe can fetch data (blob: URLs fail cross-origin).
        const origin = window.location.origin;
        const dataUrl = `${origin}/api/embedding-map/data`;
        const gridUrl = `${origin}/api/embedding-map/grid`;
        const params = new URLSearchParams({
          dataURL: dataUrl,
          gridURL: gridUrl,
        });

        setWizUrl(`/wizmap/?${params.toString()}`);
        setLoading(false);
      } catch (err) {
        if (isMounted) {
          setError(err.message || "Failed to load embedding map.");
          setLoading(false);
        }
      }
    };

    buildMap();

    return () => {
      isMounted = false;
    };
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen text-white py-12">
        <h1 className="text-4xl font-black tracking-tight mb-2">
          Embedding Map
        </h1>
        <p className="text-neutral-400 max-w-2xl mb-8">
          Generating 2D projection of log cluster embeddings via UMAP...
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen text-white py-12">
        <h1 className="text-4xl font-black tracking-tight mb-2">
          Embedding Map
        </h1>
        <div className="ui-card p-6 rounded-2xl border border-rose-500/30 bg-rose-500/5 mt-8">
          <p className="text-rose-400">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="py-8">
      <div className="mb-6">
        <h1 className="text-4xl font-black tracking-tight mb-2">
          Embedding Map
        </h1>
        <p className="text-neutral-400 max-w-2xl">
          Interactive 2D visualization of {count} log clusters. Each point is a
          semantic error pattern — zoom and hover to explore clusters.
        </p>
      </div>
      <div
        className="ui-card rounded-3xl border border-neutral-800 overflow-hidden bg-black"
        style={{ height: "75vh" }}
      >
        <iframe
          src={wizUrl}
          title="WizMap Embedding Visualization"
          style={{ width: "100%", height: "100%", border: "none" }}
          allowFullScreen
        />
      </div>
    </div>
  );
}

export default EmbeddingMap;
