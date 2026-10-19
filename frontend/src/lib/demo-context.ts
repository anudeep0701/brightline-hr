"use client";
import { createContext, useContext } from "react";

export const DemoAccessContext = createContext(false);
export const useDemoAccess = () => useContext(DemoAccessContext);
