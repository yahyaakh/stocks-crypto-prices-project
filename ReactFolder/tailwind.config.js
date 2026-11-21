export default {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx}",
    "./node_modules/@tremor/**/*.{js,jsx}",
  ],
  safelist: [
  { pattern: /bg-(blue|green|red|yellow|emerald|orange)-(100|500|600)/ },
  { pattern: /text-(blue|green|red|yellow|emerald|orange)-(500|700)/ },
  { pattern: /ring-(blue|green|red|yellow|emerald|orange)-(200)/ },
],
  theme: { extend: {} },
  plugins: [],
}