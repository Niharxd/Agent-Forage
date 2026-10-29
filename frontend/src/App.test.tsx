import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("application scaffold", () => {
  it("renders the application name without implementing workflow behavior", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "AgentForge" })).toBeInTheDocument();
    expect(screen.getByText(/workflow features are not implemented yet/i)).toBeInTheDocument();
  });
});
