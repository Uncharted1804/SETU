/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Escape hatch for a teammate running the backend on another origin.
   *  Empty (the default, and the value in the built demo app) means SAME ORIGIN. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
