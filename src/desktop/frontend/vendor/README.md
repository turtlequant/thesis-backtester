# Vendored frontend dependencies

These files are kept in the desktop bundle so the local application can render
without reaching a public CDN during startup.

- `vue.global.prod.js`: Vue 3.4.21, MIT license (`LICENSE.vue.txt`)
- `marked.min.js`: marked 12.0.1, MIT license (`LICENSE.marked.md`)

When upgrading either dependency, update the version here, the asset, and its
license file together.
