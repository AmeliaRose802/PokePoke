import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'clover'],
      reportsDirectory: './coverage',
      thresholds: {
        lines: 60,
        branches: 50,
        functions: 60,
        statements: 55,
      },
      exclude: [
        'node_modules/**',
        'src/test/**',
        '**/*.test.*',
        '**/*.config.*',
        'dist/**',
        'coverage/**',
      ],
    },
  },
});
