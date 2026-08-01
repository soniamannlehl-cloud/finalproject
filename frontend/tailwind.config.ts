/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: "#2563eb", dark: "#1d4ed8" },
      },
    },
  },
  plugins: [],
};
