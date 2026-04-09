import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // 1. Output directly to your Django 'static' folder
    outDir: '../myproject/static',
    
    // 2. CRITICAL: Set to false so it doesn't delete the other files (like style.css)
    emptyOutDir: false, 

    // 3. Force consistent filenames (No random hashes)
    rollupOptions: {
      output: {
        entryFileNames: 'react-watchlist.js', // Forces the JS name
        assetFileNames: (assetInfo) => {
          // Forces the CSS name
          if (assetInfo.name && assetInfo.name.endsWith('.css')) {
            return 'react-watchlist.css';
          }
          return '[name][extname]';
        },
      },
    },
  },
})