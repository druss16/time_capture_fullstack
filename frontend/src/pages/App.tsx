import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "../auth/AuthProvider";
import ProtectedRoute from "../routes/ProtectedRoute";
import DailyReview from "./DailyReview";
import TimecardReview from "./TimecardReview";
import TimecardSummary from "./TimecardSummary"; // ✅ NEW
import OrganizationSettings from "./OrganizationSettings";
import Login from "./Login";

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Default route → Daily Review */}
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <DailyReview />
              </ProtectedRoute>
            }
          />

          {/* Timecard Review (existing) */}
          <Route
            path="/timecards"
            element={
              <ProtectedRoute>
                <TimecardReview />
              </ProtectedRoute>
            }
          />

          {/* ✅ NEW: Timecard Summary */}
          <Route
            path="/summary"
            element={
              <ProtectedRoute>
                <TimecardSummary />
              </ProtectedRoute>
            }
          />

          {/* Organization Settings */}
          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <OrganizationSettings />
              </ProtectedRoute>
            }
          />

          {/* Login (only if auth is enabled) */}
          {!AUTH_DISABLED && <Route path="/login" element={<Login />} />}
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}