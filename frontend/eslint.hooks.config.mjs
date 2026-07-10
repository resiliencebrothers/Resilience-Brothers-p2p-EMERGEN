import reactHooks from 'eslint-plugin-react-hooks';
import localRules from './eslint-rules/no-dialog-without-scroll.mjs';

export default [{
  files: ['src/**/*.{js,jsx}'],
  plugins: {
    'react-hooks': reactHooks,
    // Local plugin — see /app/frontend/eslint-rules/no-dialog-without-scroll.js
    // Prevents the "modal without scroll" regression that shipped Feb 2026.
    'rb-local': localRules,
  },
  languageOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
  rules: {
    'react-hooks/exhaustive-deps': 'warn',
    'react-hooks/rules-of-hooks': 'error',
    'rb-local/no-dialog-without-scroll': 'error',
  }
}];
