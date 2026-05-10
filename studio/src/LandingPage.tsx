import { Link } from "react-router-dom";
import {
  ArrowRight,
  Bot,
  Cpu,
  Film,
  Lock,
  Play,
  Server,
  Sparkles,
  Users,
  Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const btnPrimary = "inline-flex items-center gap-2 rounded-xl bg-rose-600 hover:bg-rose-500 px-6 py-2.5 text-sm font-semibold text-white transition shadow-lg shadow-rose-500/20";
const btnOutline = "inline-flex items-center gap-2 rounded-xl border border-gray-700 hover:border-gray-500 px-6 py-2.5 text-sm font-semibold text-gray-300 hover:text-white transition";

function GitHubIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
    </svg>
  );
}

/* ── Navbar ── */
function Navbar() {
  return (
    <nav className="fixed top-0 inset-x-0 z-50 h-14 border-b border-gray-800/60 bg-black/90 backdrop-blur-xl flex items-center px-6">
      <div className="max-w-6xl mx-auto w-full flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-rose-500 via-fuchsia-500 to-amber-400 flex items-center justify-center">
            <Sparkles className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="font-bold text-sm tracking-tight text-white">
            <span className="text-rose-400">Nemo</span>flix
          </span>
        </div>

        <div className="flex items-center gap-2">
          <a
            href="https://github.com/ortegarod/nemoflix"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs text-gray-500 hover:text-gray-200 transition"
          >
            <GitHubIcon className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">GitHub</span>
          </a>
          <Link
            to="/studio"
            className="inline-flex items-center gap-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 px-3 py-1.5 text-xs font-semibold text-white transition"
          >
            Launch Studio <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </div>
    </nav>
  );
}

/* ── Hero ── */
function Hero() {
  return (
    <section className="min-h-screen flex items-center justify-center pt-14 px-6">
      <div className="max-w-4xl text-center">
        <Badge
          className="mb-8 gap-1.5 border-amber-500/30 bg-amber-500/5 text-amber-300 h-7 px-3"
          variant="outline"
        >
          <Cpu className="w-3.5 h-3.5" />
          AMD MI300X · 192 GB VRAM · Open Source
        </Badge>

        <h1 className="text-5xl md:text-7xl font-bold leading-tight tracking-tight mb-6 text-white">
          Put Yourself
          <br />
          <span className="bg-gradient-to-r from-rose-400 via-fuchsia-400 to-amber-400 bg-clip-text text-transparent">
            In the Film.
          </span>
        </h1>

        {/* Hero video — phone-sized preview right under headline */}
        <div className="mx-auto max-w-xs sm:max-w-sm md:max-w-md mb-10">
          <div className="rounded-[1.5rem] overflow-hidden border border-gray-800/60 bg-gray-950 shadow-2xl shadow-rose-500/10 ring-1 ring-white/5 aspect-square">
            <video
              src="/demos/iron-man-flight.mp4"
              controls
              poster=""
              className="w-full h-full object-cover"
              preload="metadata"
              autoPlay
              muted
              loop
              playsInline
            />
          </div>
          <div className="flex items-center justify-center gap-2 mt-2">
            <span className="text-[10px] text-gray-600 uppercase tracking-wider">Wan 2.2 I2V · AMD MI300X</span>
          </div>
        </div>

        <p className="text-xl text-gray-400 max-w-2xl mx-auto mb-10 leading-relaxed">
          Upload a few photos. Build a model of yourself. Generate photorealistic
          images in any scene you can imagine. Animate them into short films.
          <span className="text-white font-medium"> Make the impossible, possible.</span>
        </p>

        <div className="flex flex-col items-center gap-3">
          <Link to="/studio" className={btnPrimary}>
            <Sparkles className="w-4 h-4" />
            Launch Studio
          </Link>
          <a
            href="https://github.com/ortegarod/nemoflix"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-gray-500 hover:text-gray-300 transition"
          >
            View on GitHub →
          </a>
        </div>

        <p className="mt-8 text-xs text-gray-700">
          Self-hosted · Agent-native · MIT License
        </p>
      </div>
    </section>
  );
}

/* ── Three pillars ── */
function Pillars() {
  const items = [
    {
      icon: Cpu,
      color: "text-amber-400",
      border: "border-amber-500/20",
      bg: "from-amber-950/20",
      label: "AMD MI300X",
      body: "Fine-tune Flux.2 LoRAs on 192 GB VRAM via ROCm. ~90 minutes to a consistent character. No CUDA.",
    },
    {
      icon: Bot,
      color: "text-rose-400",
      border: "border-rose-500/20",
      bg: "from-rose-950/20",
      label: "Agent Skill File",
      body: "Agent reading this? Pull the repo and read SKILL.md. Every endpoint, every workflow, every parameter. One file. No SDK.",
    },
    {
      icon: Film,
      color: "text-fuchsia-400",
      border: "border-fuchsia-500/20",
      bg: "from-fuchsia-950/20",
      label: "Image + Video",
      body: "Photorealistic Flux.2 images and Wan 2.2 I2V animation on the same pipeline. One character, every format.",
    },
  ];

  return (
    <section className="py-20 px-6 border-y border-gray-800/40">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-12">
          <h2 className="text-3xl font-bold text-white mb-3">The Stack</h2>
          <p className="text-gray-500">GPU, pipeline, and agent integration in one system.</p>
        </div>
        <div className="grid md:grid-cols-3 gap-5">
        {items.map((item) => (
          <Card
            key={item.label}
            className={`border ${item.border} bg-gradient-to-b ${item.bg} to-gray-950/60 ring-0`}
          >
            <CardHeader>
              <item.icon className={`w-5 h-5 ${item.color} mb-1`} />
              <CardTitle className="text-white text-sm">{item.label}</CardTitle>
            </CardHeader>
            <CardContent>
              <CardDescription className="text-gray-400 leading-relaxed">
                {item.body}
              </CardDescription>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  </section>
  );
}

/* ── Feature Film Showcase ── */
function FeatureFilmShowcase() {
  return (
    <section className="py-16 px-6 border-y border-gray-800/40 bg-gradient-to-b from-black via-gray-950/30 to-black">
      <div className="max-w-6xl mx-auto">
        {/* Section headline */}
        <div className="text-center mb-12">
          <Badge className="mb-4 gap-1.5 border-fuchsia-500/20 bg-fuchsia-500/5 text-fuchsia-300 h-7 px-3" variant="outline">
            <Film className="w-3.5 h-3.5" />
            Your Model. Your Film. Minutes.
          </Badge>
          <h2 className="text-4xl md:text-5xl font-bold text-white mb-5">
            You and Your Agent.
            <br />
            <span className="bg-gradient-to-r from-rose-400 via-fuchsia-400 to-amber-400 bg-clip-text text-transparent">
              Co-Directing a Film.
            </span>
          </h2>
          <p className="text-lg text-gray-500 max-w-2xl mx-auto leading-relaxed">
            This is what your film looks like. Once your model is trained from your photos,
            you and your agent can assemble scenes, shots, and final cuts in minutes —
            not the hours or days it used to take. You bring the vision. Your agent handles the rest.
          </p>
        </div>

        {/* Film title card */}
        <div className="max-w-2xl mx-auto mb-6 text-center">
          <div className="flex items-center justify-center gap-2 mb-3">
            <Badge className="gap-1 border-fuchsia-500/20 bg-fuchsia-500/5 text-fuchsia-300 text-[10px]" variant="outline">
              <Film className="w-3 h-3" /> Full Project Render
            </Badge>
            <span className="text-xs text-gray-500">Multi-shot · assembled · AMD MI300X</span>
          </div>
          <p className="text-[10px] uppercase tracking-[0.2em] text-amber-400 font-medium mb-1">Official Selection — AMD Developer Hackathon 2026</p>
          <h3 className="text-xl font-bold text-white">Nemoflix: A Debut Feature</h3>
          <p className="text-xs text-gray-500 mt-0.5">LabLab.ai · World Premiere</p>
        </div>

        {/* The Film */}
        <div className="max-w-2xl mx-auto">
          <div className="rounded-2xl overflow-hidden border border-gray-800/60 bg-gray-950 shadow-2xl shadow-fuchsia-500/5 aspect-square">
            <video
              src="/demos/feature-film.mp4"
              controls
              poster=""
              className="w-full h-full object-cover"
              preload="metadata"
            />
          </div>

          <div className="mt-6 flex justify-center">
            <Link
              to="/studio/projects"
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-700 hover:border-rose-500/50 px-4 py-2 text-xs font-medium text-gray-300 hover:text-white transition"
            >
              Try It Yourself <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── How It Works ── */
function HowItWorks() {
  const steps = [
    {
      n: "01",
      color: "text-amber-400",
      ring: "ring-amber-500/30",
      title: "Train Your Character LoRA",
      body: "Upload 15–25 reference photos. Nemoflix fine-tunes a Flux.2 LoRA on AMD MI300X — 192 GB VRAM, ROCm, no CUDA. ~90 minutes to a character that looks consistent in every single frame.",
      aside: (
        <Card className="border-amber-500/20 bg-gradient-to-b from-amber-950/20 to-gray-950/60 ring-0">
          <CardHeader>
            <Badge className="w-fit gap-1.5 border-amber-500/20 bg-amber-500/5 text-amber-400" variant="outline">
              <Cpu className="w-3 h-3" /> AMD MI300X
            </Badge>
            <CardTitle className="text-white text-sm mt-2">Training Config</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1.5 font-mono text-xs text-gray-400">
              {[
                ["model", "flux.2-dev"],
                ["vram", "192 GB"],
                ["runtime", "~90 min"],
                ["steps", "1000"],
                ["framework", "ROCm 7.2"],
              ].map(([k, v]) => (
                <p key={k}>
                  <span className="text-gray-600 inline-block w-20">{k}</span>
                  {v}
                </p>
              ))}
            </div>
          </CardContent>
        </Card>
      ),
    },
    {
      n: "02",
      color: "text-rose-400",
      ring: "ring-rose-500/30",
      title: "Generate Images via API",
      body: "Your AI agent calls the API with a prompt and character ID. Nemoflix builds the ComfyUI workflow, routes to the right GPU node, queues the job, and returns a prompt ID. Photorealistic results in seconds.",
      aside: (
        <Card className="border-gray-800 bg-gray-950 ring-0">
          <CardHeader>
            <CardTitle className="text-xs text-gray-500 font-mono font-normal">API call</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 font-mono text-xs">
            <p className="text-gray-500">
              POST <span className="text-rose-400">/api/image/generate</span>
            </p>
            <div className="rounded-lg bg-black/60 p-3 space-y-1 text-gray-400">
              <p className="text-gray-600">{"{"}</p>
              <p className="pl-3">
                <span className="text-amber-300">"character"</span>:{" "}
                <span className="text-emerald-300">"rigo"</span>,
              </p>
              <p className="pl-3">
                <span className="text-amber-300">"prompt"</span>:{" "}
                <span className="text-emerald-300">"walking through a rainy street"</span>
              </p>
              <p className="text-gray-600">{"}"}</p>
            </div>
            <p className="text-emerald-400/70 pt-1">← prompt_id: a3f9c1d2</p>
          </CardContent>
        </Card>
      ),
    },
    {
      n: "03",
      color: "text-fuchsia-400",
      ring: "ring-fuchsia-500/30",
      title: "Animate to Video",
      body: "One more API call and Wan 2.2 I2V animates the image into a short video clip. The same character, moving. String clips together into a full scene. Your agent builds the whole sequence autonomously.",
      aside: (
        <Card className="border-fuchsia-500/20 bg-gradient-to-b from-fuchsia-950/20 to-gray-950/60 ring-0">
          <CardHeader>
            <Badge className="w-fit gap-1.5 border-fuchsia-500/20 bg-fuchsia-500/5 text-fuchsia-400" variant="outline">
              Wan 2.2 I2V
            </Badge>
            <CardTitle className="text-white text-sm mt-2">Video Config</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1.5 font-mono text-xs text-gray-400">
              {[
                ["model", "wan2.2-i2v-14b"],
                ["input", "still image"],
                ["output", "5s video clip"],
                ["cfg", "3.5 · steps 20"],
              ].map(([k, v]) => (
                <p key={k}>
                  <span className="text-gray-600 inline-block w-20">{k}</span>
                  {v}
                </p>
              ))}
            </div>
            <p className="text-[11px] text-fuchsia-300/50 mt-4">
              Same character. Real motion. Not a filter.
            </p>
          </CardContent>
        </Card>
      ),
    },
    {
      n: "04",
      color: "text-emerald-400",
      ring: "ring-emerald-500/30",
      title: "Build Films Scene by Scene",
      body: "Projects hold Scenes, Scenes hold Shots — each with its own generated image and video. When every shot is animated, hit render and Nemoflix stitches the whole thing together into one finished video. Your agent wrote, directed, and rendered a short film, start to finish.",
      aside: (
        <Card className="border-emerald-500/20 bg-gradient-to-b from-emerald-950/20 to-gray-950/60 ring-0">
          <CardHeader>
            <Badge className="w-fit gap-1.5 border-emerald-500/20 bg-emerald-500/5 text-emerald-400" variant="outline">
              <Film className="w-3 h-3" /> Projects
            </Badge>
            <CardTitle className="text-white text-sm mt-2">Film Structure</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="font-mono text-xs space-y-2">
              <div className="text-emerald-300/80">
                Project <span className="text-emerald-500">"Neon Nights"</span>
              </div>
              <div className="pl-4 border-l border-gray-800 space-y-1.5">
                <div className="text-gray-400">
                  Scene 1 <span className="text-gray-600">"Alley Chase"</span>
                </div>
                <div className="pl-4 text-gray-600 space-y-0.5">
                  <div>Shot 1A → image + video</div>
                  <div>Shot 1B → image + video</div>
                </div>
                <div className="text-gray-400 pt-1">
                  Scene 2 <span className="text-gray-600">"Rooftop"</span>
                </div>
              </div>
            </div>
            <p className="text-[11px] text-emerald-300/50 mt-4">
              One API. Train → generate → animate → render.
            </p>
          </CardContent>
        </Card>
      ),
    },
  ];

  return (
    <section className="py-28 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-20">
          <h2 className="text-4xl font-bold text-white mb-4">How It Works</h2>
          <p className="text-gray-500 text-lg">
            From reference photos to a finished film in four steps.
          </p>
        </div>

        <div className="space-y-24">
          {steps.map((step, i) => (
            <div key={step.n} className="grid md:grid-cols-2 gap-12 items-center">
              <div className={i % 2 === 1 ? "md:order-2" : ""}>
                <div
                  className={`w-10 h-10 rounded-full ring-1 ${step.ring} bg-gray-950 flex items-center justify-center mb-4`}
                >
                  <span className={`text-xs font-bold font-mono ${step.color}`}>
                    {step.n}
                  </span>
                </div>
                <h3 className="text-3xl font-bold text-white mb-4">{step.title}</h3>
                <p className="text-gray-400 text-lg leading-relaxed">{step.body}</p>
              </div>
              <div className={i % 2 === 1 ? "md:order-1" : ""}>{step.aside}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── Features grid ── */
function Features() {
  const features = [
    { icon: Cpu, color: "text-amber-400", title: "LoRA Training on AMD", body: "Fine-tune Flux.2 on AMD MI300X via ROCm. No CUDA required. Monitor job progress live in the Studio." },
    { icon: Server, color: "text-rose-400", title: "Self-Hosted", body: "Your hardware, your models, your data. No cloud dependency, no rate limits, no data leaving your machine." },
    { icon: Bot, color: "text-violet-400", title: "Agent API", body: "REST API any agent can call. Characters, images, video, training jobs — all simple HTTP endpoints." },
    { icon: Users, color: "text-fuchsia-400", title: "Character Registry", body: "Register characters with trigger words and LoRA weights. Every generation references them consistently." },
    { icon: Zap, color: "text-emerald-400", title: "Multi-GPU Routing", body: "Images and video automatically routed to the right node. Add more GPUs without changing any code." },
    { icon: Lock, color: "text-blue-400", title: "Open Source", body: "MIT license. Audit the code, fork it, extend it. No black boxes." },
  ];

  return (
    <section className="py-28 px-6 border-t border-gray-800/40">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-4xl font-bold text-white mb-4">What's Inside</h2>
          <p className="text-gray-500 text-lg">
            Everything you need to run a visual AI studio.
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-5">
          {features.map((f) => (
            <Card
              key={f.title}
              className="border-gray-800/60 bg-gray-950/50 ring-0 hover:border-gray-700 transition-colors"
            >
              <CardHeader>
                <f.icon className={`w-5 h-5 ${f.color}`} />
                <CardTitle className="text-white text-sm mt-3">{f.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-gray-500 leading-relaxed">
                  {f.body}
                </CardDescription>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── CTA ── */
function CTA() {
  return (
    <section className="py-32 px-6">
      <div className="max-w-2xl mx-auto text-center">
        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-rose-500 via-fuchsia-500 to-amber-400 flex items-center justify-center mx-auto mb-8 shadow-2xl shadow-rose-500/20">
          <Sparkles className="w-7 h-7 text-white" />
        </div>
        <h2 className="text-4xl md:text-5xl font-bold text-white mb-6">
          Ready to Run It?
        </h2>
        <p className="text-xl text-gray-400 mb-10 leading-relaxed">
          Clone the repo, point it at your GPU nodes, and your agent is
          generating in minutes.
        </p>
        <div className="flex items-center justify-center gap-3 flex-wrap">
          <Link to="/studio" className={btnPrimary}>
            <Sparkles className="w-4 h-4" />
            Launch Studio
          </Link>
          <a
            href="https://github.com/ortegarod/nemoflix"
            target="_blank"
            rel="noopener noreferrer"
            className={btnOutline}
          >
            <GitHubIcon className="w-4 h-4" />
            View on GitHub
          </a>
        </div>
      </div>
    </section>
  );
}

/* ── Footer ── */
function Footer() {
  return (
    <footer className="border-t border-gray-800/40 py-10 px-6">
      <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
        <span className="text-sm font-bold">
          <span className="text-rose-400">Nemo</span>
          <span className="text-gray-500">flix</span>
        </span>
        <div className="flex items-center gap-6 text-xs text-gray-600">
          <a
            href="https://github.com/ortegarod/nemoflix"
            target="_blank"
            rel="noreferrer"
            className="hover:text-gray-400 transition"
          >
            GitHub
          </a>
          <Link to="/studio" className="hover:text-gray-400 transition">
            Studio
          </Link>
          <span>© {new Date().getFullYear()} Nemoflix · MIT License</span>
        </div>
      </div>
    </footer>
  );
}

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-black text-white">
      <Navbar />
      <Hero />
      <Pillars />
      <FeatureFilmShowcase />
      <HowItWorks />
      <Features />
      <CTA />
      <Footer />
    </div>
  );
}
