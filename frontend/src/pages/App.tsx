import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "../auth/AuthProvider";
import ProtectedRoute from "../routes/ProtectedRoute";
import DailyReview from "./DailyReview";
import TimecardReview from "./TimecardReview";
import OrganizationSettings from "./OrganizationSettings";
import Login from "./Login";

const AUTH_DISABLED = import.meta.env.VITE_AUTH_DISABLED === "true";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <DailyReview />
              </ProtectedRoute>
            }
          />
          <Route
            path="/timecards"
            element={
              <ProtectedRoute>
                <TimecardReview />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <OrganizationSettings />
              </ProtectedRoute>
            }
          />
          {!AUTH_DISABLED && <Route path="/login" element={<Login />} />}
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}