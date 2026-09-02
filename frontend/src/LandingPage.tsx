import { lazy, Suspense, useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import './LandingPage.css'

const LivingScene = lazy(() => import('./components/LivingScene'))

const SHEETS = [
  { id: 'survey', code: 'A–01', label: 'Survey' },
  { id: 'structure', code: 'S–02', label: 'Structure' },
  { id: 'paths', code: 'S–03', label: 'Load paths' },
  { id: 'faults', code: 'D–04', label: 'Faults' },
  { id: 'boundaries', code: 'G–05', label: 'Boundaries' },
  { id: 'certification', code: 'C–06', label: 'Certification' },
] as const

function useReducedMotion() {
  const [reduced, setReduced] = useState(false)
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setReduced(media.matches)
    update()
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  return reduced
}

function useScrollProgress() {
  const [progress, setProgress] = useState(0)
  useEffect(() => {
    let frame = 0
    const update = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const available = document.documentElement.scrollHeight - window.innerHeight
        setProgress(available > 0 ? Math.min(1, Math.max(0, window.scrollY / available)) : 0)
      })
    }
    update()
    window.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
    }
  }, [])
  return progress
}

function jumpTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
}

export function LandingPage() {
  const progress = useScrollProgress()
  const reduced = useReducedMotion()
  const active = Math.min(SHEETS.length - 1, Math.floor(progress * SHEETS.length))

  return (
    <div className="landing" data-sheet={active + 1} style={{ '--story-progress': progress } as CSSProperties}>
      <a className="skip-story" href="#workflow">Skip 3D sequence</a>
      <div className="art-stage" aria-hidden="true">
        <img src="/art/vinyas-living-drawing.webp" alt="" />
        <span className="art-axis horizontal" /><span className="art-axis vertical" />
        <span className="art-note note-one">SYSTEM ELEVATION / LIVE</span>
        <span className="art-note note-two">EVIDENCE PLANE 04</span>
      </div>
      <div className="analysis-overlay" aria-hidden="true">
        <Suspense fallback={null}><LivingScene progress={progress} reduced={reduced} /></Suspense>
      </div>
      <header className="landing-nav">
        <a className="wordmark" href="#top" aria-label="Vinyas home"><span>वि</span> VINYAS</a>
        <nav aria-label="Primary navigation">
          <a href="#workflow">How it works</a>
          <a href="#governance">Governance</a>
          <a href="/app">Open analyzer</a>
          <a className="nav-cta" href="https://github.com/Kshitijmishradev/Vinyas">GitHub <span aria-hidden="true">↗</span></a>
        </nav>
        <a className="mobile-launch" href="/app">OPEN APP <span aria-hidden="true">↗</span></a>
      </header>

      <aside className="sheet-index" aria-label="Drawing index">
        <span className="index-label">DRAWING SET · 01/01</span>
        {SHEETS.map((sheet, index) => (
          <button key={sheet.id} className={active === index ? 'active' : ''} onClick={() => jumpTo(sheet.id)} aria-label={`Go to ${sheet.label}`}>
            <span>{sheet.code}</span><i /><b>{sheet.label}</b>
          </button>
        ))}
      </aside>
      <div className="story-progress" aria-hidden="true"><span style={{ transform: `scaleX(${progress})` }} /></div>

      <main className="landing-story" id="top">
        <section className="story-panel hero" id="survey">
          <span className="chapter-ghost" aria-hidden="true">01</span>
          <div className="story-copy">
            <p className="drawing-number">A–01 / REPOSITORY SURVEY</p>
            <h1><span>Map your</span><span>codebase.</span><em>Govern every change.</em></h1>
            <p className="lede">Vinyas turns imports, modules, and boundaries into an evidence-backed architectural map—then keeps new violations out of CI.</p>
            <div className="hero-actions">
              <a className="landing-button primary" href="/app">Analyze a repository <span>→</span></a>
              <a className="landing-button quiet" href="#structure">See how it works</a>
            </div>
            <div className="command-strip" aria-label="Command line quick start">
              <span>$</span><code>architect analyze ./repository</code><small>LOCAL · DETERMINISTIC</small>
            </div>
            <div className="survey-readout" aria-label="Example repository summary"><span><b>214</b> modules</span><span><b>486</b> edges</span><span><b>07</b> findings</span><span><b>02</b> cycles</span></div>
          </div>
          <p className="figure-caption"><span>FIG. 01</span> A system under survey. Every visible connection is supported by source evidence.</p>
        </section>

        <section className="story-panel" id="structure">
          <span className="anchor-target" id="workflow" aria-hidden="true" />
          <span className="chapter-ghost" aria-hidden="true">02</span>
          <div className="story-copy compact">
            <p className="drawing-number">S–02 / STRUCTURAL SYSTEM</p>
            <h2>See the system<br />behind the files.</h2>
            <p>Vinyas resolves Python and JavaScript/TypeScript dependencies without guessing ambiguous edges. Isolated files remain visible. Every relationship has a location, method, and confidence.</p>
            <div className="technical-note"><span>01</span><p><strong>Deterministic by construction</strong>AI can explain a verified finding. It never decides whether the architecture passes.</p></div>
          </div>
        </section>

        <section className="story-panel align-right" id="paths">
          <span className="chapter-ghost" aria-hidden="true">03</span>
          <div className="story-copy compact">
            <p className="drawing-number">S–03 / LOAD PATHS</p>
            <h2>Trace impact before<br />it becomes risk.</h2>
            <p>Follow incoming and outgoing dependencies, expose deep coupling, and understand the impact radius of a change before it reaches review.</p>
            <ul className="signal-list"><li><i className="lime" />Verified relationship</li><li><i />Resolved dependency</li><li><i className="red" />Cycle participation</li></ul>
          </div>
        </section>

        <section className="story-panel" id="faults">
          <span className="chapter-ghost" aria-hidden="true">04</span>
          <div className="story-copy compact">
            <p className="drawing-number">D–04 / FAULT REGISTER</p>
            <h2>Faults arrive<br />with evidence.</h2>
            <p>Cycles, unresolved imports, excessive fan-out, and cross-boundary coupling are reported with precise source locations—not opaque risk scores.</p>
            <div className="finding-sample"><span>CYCLE</span><code>api/router.ts:18 → domain/order.ts</code><b>NEW</b></div>
          </div>
        </section>

        <section className="story-panel align-right" id="boundaries">
          <span className="chapter-ghost" aria-hidden="true">05</span>
          <div className="story-copy compact" id="governance">
            <p className="drawing-number">G–05 / GOVERNING PLANES</p>
            <h2>Make architecture<br />an enforceable contract.</h2>
            <p>Declare layers, ownership boundaries, allowed directions, thresholds, and reasoned suppressions in one reviewable configuration.</p>
            <pre className="config-sample"><span>layers:</span>{'\n'}  web: <i>[frontend/**]</i>{'\n'}  core: <i>[src/domain/**]</i>{'\n'}<span>forbid:</span> web → data</pre>
          </div>
        </section>

        <section className="story-panel final-panel" id="certification">
          <span className="chapter-ghost" aria-hidden="true">06</span>
          <div className="story-copy compact">
            <p className="drawing-number">C–06 / CERTIFICATION</p>
            <h2>Merge with the<br /><em>structure intact.</em></h2>
            <p>Baseline-aware enforcement blocks only newly introduced violations. Existing debt can be adopted without freezing development.</p>
            <div className="hero-actions">
              <a className="landing-button primary" href="/app">Open Vinyas <span>→</span></a>
              <a className="landing-button quiet" href="https://github.com/Kshitijmishradev/Vinyas">Read the source ↗</a>
            </div>
          </div>
          <footer><span>VINYAS / विन्यास</span><p>Architecture governance for real codebases.</p><a href="#top">Back to survey ↑</a></footer>
        </section>
      </main>
    </div>
  )
}
