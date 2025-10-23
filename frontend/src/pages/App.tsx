import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "../auth/AuthProvider";
import ProtectedRoute from "../routes/ProtectedRoute";
import DailyReview from "./DailyReview";
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
          {!AUTH_DISABLED && <Route path="/login" element={<Login />} />}
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
