import { useState } from "react";
import { Check, Trash2, X, Play, Wand2, ArrowRight } from "lucide-react";
import type { MediaItem } from "../types";

interface MediaTileProps {
  item: MediaItem;
  onOpen: () => void;
  onDelete: (item: MediaItem) => Promise<void> | void;
  onGenerateVideo?: (item: MediaItem, motionPrompt: string) => void;
}

export function MediaTile({ item, onOpen, onDelete, onGenerateVideo }: MediaTileProps) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [showI2VInput, setShowI2VInput] = useState(false);
  const [motionPrompt, setMotionPrompt] = useState("");

  async function confirm(event: React.MouseEvent) {
    event.stopPropagation();
    if (deleting) return;
    setDeleting(true);
    try {
      await onDelete(item);
    } finally {
      setDeleting(false);
      setConfirmDelete(false);
    }
  }

  return (
    <div
      onClick={onOpen}
      className="cursor-pointer rounded-xl overflow-hidden border border-gray-800/60 hover:border-gray-600 aspect-[3/4] bg-gray-900/50 relative group transition-all duration-200 hover:shadow-xl hover:shadow-black/30 hover:-translate-y-0.5"
    >
      {/* Media */}
      {item.type === "video" ? (
        <video src={item.thumb || item.url} className="w-full h-full object-cover" preload="metadata" muted />
      ) : (
        <img src={item.thumb || item.url} alt={item.name || ""} className="w-full h-full object-cover group-hover:scale-105 transition duration-500" loading="lazy" />
      )}

      {/* Delete button */}
      {!confirmDelete && (
        <button
          onClick={(event) => {
            event.stopPropagation();
            setConfirmDelete(true);
          }}
          className="absolute top-2 right-2 z-10 w-8 h-8 rounded-lg bg-black/60 text-white/80 backdrop-blur-sm flex items-center justify-center opacity-0 group-hover:opacity-100 hover:bg-red-600 hover:text-white transition-all"
          title="Delete"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      )}

      {/* I2V button / prompt — only for images */}
      {!confirmDelete && item.type === "image" && onGenerateVideo && (
        <>
          {!showI2VInput ? (
            <button
              onClick={(event) => {
                event.stopPropagation();
                setShowI2VInput(true);
              }}
              className="absolute top-2 left-2 z-10 flex items-center gap-1.5 rounded-lg bg-violet-600/80 text-white text-[10px] font-medium px-2 py-1.5 backdrop-blur-sm opacity-0 group-hover:opacity-100 hover:bg-violet-500 transition-all"
              title="Generate Video"
            >
              <Wand2 className="w-3 h-3" />
              I2V
            </button>
          ) : (
            <div
              className="absolute inset-0 z-20 bg-black/90 backdrop-blur-sm flex flex-col items-center justify-center gap-2 px-4"
              onClick={(event) => event.stopPropagation()}
            >
              <p className="text-[10px] uppercase tracking-wider text-white/60">Motion Prompt</p>
              <input
                autoFocus
                value={motionPrompt}
                onChange={(e) => setMotionPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    onGenerateVideo(item, motionPrompt);
                    setShowI2VInput(false);
                    setMotionPrompt("");
                  }
                  if (e.key === "Escape") {
                    setShowI2VInput(false);
                    setMotionPrompt("");
                  }
                }}
                placeholder="camera push in, rain falling..."
                className="w-full rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-xs text-white focus:outline-none focus:border-violet-500 placeholder:text-gray-600"
              />
              <div className="flex gap-2">
                <button
                  onClick={() => {
                    setShowI2VInput(false);
                    setMotionPrompt("");
                  }}
                  className="text-[10px] text-gray-500 hover:text-white transition"
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    onGenerateVideo(item, motionPrompt);
                    setShowI2VInput(false);
                    setMotionPrompt("");
                  }}
                  className="flex items-center gap-1 text-[10px] text-violet-400 hover:text-violet-200 transition font-medium"
                >
                  Generate <ArrowRight className="w-3 h-3" />
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Bottom info bar */}
      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 via-black/40 to-transparent p-3 pt-6 opacity-0 group-hover:opacity-100 transition pointer-events-none">
        <p className="text-xs font-medium truncate text-white/90">{item.name || "Untitled"}</p>
      </div>

      {/* Video badge */}
      {item.type === "video" && (
        <div className="absolute top-2 left-2 bg-black/60 backdrop-blur-sm text-white text-[10px] font-medium px-2 py-1 rounded-md flex items-center gap-1">
          <Play className="w-2.5 h-2.5 fill-white" />
          VIDEO
        </div>
      )}

      {/* Delete confirmation overlay */}
      {confirmDelete && (
        <div
          className="absolute inset-0 z-20 bg-black/80 backdrop-blur-sm flex flex-col items-center justify-center gap-3"
          onClick={(event) => {
            event.stopPropagation();
            setConfirmDelete(false);
          }}
        >
          <span className="text-xs font-semibold uppercase tracking-wider text-white/80">Delete this?</span>
          <div className="flex gap-3" onClick={(event) => event.stopPropagation()}>
            <button
              onClick={() => setConfirmDelete(false)}
              className="w-10 h-10 rounded-full bg-gray-800/90 text-gray-400 hover:text-white hover:bg-gray-700 flex items-center justify-center transition"
              title="Cancel"
            >
              <X className="w-5 h-5" />
            </button>
            <button
              onClick={confirm}
              disabled={deleting}
              className="w-10 h-10 rounded-full bg-red-600/90 text-white hover:bg-red-500 disabled:bg-gray-800 disabled:text-gray-600 flex items-center justify-center transition"
              title="Confirm delete"
            >
              <Check className="w-5 h-5" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
