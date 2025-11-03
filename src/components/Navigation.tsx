// src/components/Navigation.tsx
import { Clock } from "lucide-react";

export default function Navigation() {
  return (
    <nav className="border-b bg-card shadow-card sticky top-0 z-50">
      <div className="container mx-auto px-4 py-4">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-gradient-primary">
            <Clock className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-foreground">TimeTrack Pro</h1>
            <p className="text-xs text-muted-foreground">Professional Time Management for CPAs</p>
          </div>
        </div>
      </div>
    </nav>
  );
}
