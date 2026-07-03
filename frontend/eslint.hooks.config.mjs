import reactHooks from 'eslint-plugin-react-hooks';
export default [{
  files: ['src/**/*.{js,jsx}'],
  plugins: { 'react-hooks': reactHooks },
  languageOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
  rules: {
    'react-hooks/exhaustive-deps': 'warn',
    'react-hooks/rules-of-hooks': 'error',
  }
}];
