import path from 'path';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

const rawPort = process.env.PORT ?? '5173';
const port = Number(rawPort);

if (Number.isNaN(port) || port <= 0) {
  throw new Error(`Invalid PORT value: "${rawPort}"`);
}

const basePath = process.env.BASE_PATH ?? '/';
const allowedHosts = new Set(['localhost', '127.0.0.1', '.pike.replit.dev']);
for (const value of [process.env.REPLIT_DEV_DOMAIN, process.env.REPLIT_DOMAINS]) {
  for (const entry of value?.split(/[,\s]+/) ?? []) {
    if (!entry) continue;
    try {
      allowedHosts.add(new URL(entry.includes('://') ? entry : `http://${entry}`).hostname);
    } catch {
      // Ignore malformed host overrides; Vite still keeps the explicit defaults.
    }
  }
}
const viteAllowedHosts = [...allowedHosts];

export default defineConfig({
  base: basePath,
  plugins: [
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, 'src'),
      '@assets': path.resolve(
        import.meta.dirname,
        '..',
        '..',
        'attached_assets',
      ),
    },
    dedupe: ['react', 'react-dom'],
  },
  root: path.resolve(import.meta.dirname),
  build: {
    outDir: path.resolve(import.meta.dirname, 'dist/public'),
    emptyOutDir: true,
  },
  server: {
    port,
    strictPort: true,
    host: '127.0.0.1',
    allowedHosts: viteAllowedHosts,
    fs: {
      strict: true,
    },
  },
  preview: {
    port,
    host: '127.0.0.1',
    allowedHosts: viteAllowedHosts,
  },
});
