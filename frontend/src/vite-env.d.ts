/// <reference types="vite/client" />

declare module "react-plotly.js/factory" {
  import type { ComponentType } from "react";
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  export default function createPlotlyComponent(plotly: unknown): ComponentType<any>;
}

declare module "plotly.js-dist-min";
