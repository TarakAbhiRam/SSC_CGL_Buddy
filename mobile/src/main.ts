import './style.css';

type MigrationItem = {
  title: string;
  detail: string;
  state: 'ready' | 'next' | 'planned';
};

const items: MigrationItem[] = [
  {
    title: 'Capacitor shell',
    detail: 'Android now builds from a standard Vite + Capacitor project with its own Gradle wrapper.',
    state: 'ready',
  },
  {
    title: 'Shared app contract',
    detail: 'The mobile services will implement the existing frontend API contract without embedding Python.',
    state: 'ready',
  },
  {
    title: 'Question storage',
    detail: 'Port question bank, settings, and session persistence to IndexedDB with Dexie.',
    state: 'next',
  },
  {
    title: 'Imports and AI',
    detail: 'Use pdfjs-dist for PDFs and provider REST APIs for Gemini/Groq calls.',
    state: 'planned',
  },
];

const app = document.querySelector<HTMLDivElement>('#app');

if (!app) {
  throw new Error('App root not found');
}

app.innerHTML = `
  <main class="shell">
    <section class="hero" aria-labelledby="title">
      <div class="brand-row">
        <span class="mark">CB</span>
        <span>SSC CGL Buddy</span>
      </div>
      <h1 id="title">Mobile build path</h1>
      <p>
        This Android target is intentionally separate from the Python desktop runtime.
        The APK will use TypeScript services, browser storage, and Capacitor native hooks.
      </p>
    </section>

    <section class="status-panel" aria-label="Migration status">
      ${items.map((item) => `
        <article class="status-card ${item.state}">
          <div>
            <span class="pill">${item.state}</span>
            <h2>${item.title}</h2>
          </div>
          <p>${item.detail}</p>
        </article>
      `).join('')}
    </section>
  </main>
`;
