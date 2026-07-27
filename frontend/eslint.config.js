import js from '@eslint/js'
import tsParser from '@typescript-eslint/parser'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

export default [
  { ignores: ['dist/**', 'src/App.vue'] },
  js.configs.recommended,
  ...pluginVue.configs['flat/essential'],
  {
    files: ['src/**/*.ts'],
    languageOptions: { parser: tsParser, parserOptions: { sourceType: 'module' }, globals: globals.browser },
  },
  {
    files: ['src/**/*.vue'],
    languageOptions: { parserOptions: { parser: tsParser, extraFileExtensions: ['.vue'] }, globals: globals.browser },
    rules: { 'vue/multi-word-component-names': 'off' },
  },
  {
    // Test mocks use function-type parameters that the base no-unused-vars rule
    // (without the typescript-eslint plugin) mis-flags; ignore argument names
    // while still catching genuinely unused variables.
    files: ['src/**/*.test.ts'],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    rules: { 'no-unused-vars': ['error', { args: 'none' }] },
  },
  {
    // Same base-rule limitation applies to interface method and callback type
    // signatures in the P1 source (e.g. TokenStore, useAsyncResource options):
    // their parameter names are type-only. Keep unused-variable detection.
    files: ['src/**/*.ts', 'src/**/*.vue'],
    rules: { 'no-unused-vars': ['error', { args: 'none', varsIgnorePattern: '^_' }] },
  },
]
