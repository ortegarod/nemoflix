const API_BASE = "";

async function apiFetch(path: string, init?: RequestInit) {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

export async function getListing(): Promise<{ images: any[]; total: number }> {
  return apiFetch("/api/listing");
}

export async function generateVideo(params: {
  image: string;
  prompt?: string;
  width?: number;
  height?: number;
  length?: number;
  fps?: number;
}): Promise<{ ok: boolean; prompt_id: string; mode: string }> {
  return apiFetch("/api/video/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode: "i2v",
      image: params.image,
      prompt: params.prompt || "",
      width: params.width || 640,
      height: params.height || 640,
      length: params.length || 81,
      fps: params.fps || 16,
    }),
  });
}
