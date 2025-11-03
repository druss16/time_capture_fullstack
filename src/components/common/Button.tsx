import { ReactNode } from "react";
import { BUTTON_VARIANTS, DESIGN_SYSTEM } from "@/lib/design-system";

type ButtonVariant = keyof typeof BUTTON_VARIANTS;

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md" | "lg";
  icon?: ReactNode;
  children: ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  variant = "secondary",
  size = "md",
  icon,
  children,
  className,
  ...props
}) => {
  const baseClasses =
    "flex items-center gap-2 rounded-xl font-medium text-sm " +
    DESIGN_SYSTEM.transitions.base;

  const sizeClasses = {
    sm: "px-3 py-1.5",
    md: "px-4 py-2.5",
    lg: "px-5 py-3",
  };

  const variantClasses = BUTTON_VARIANTS[variant];

  return (
    <button
      className={`${baseClasses} ${sizeClasses[size]} ${variantClasses} ${
        className || ""
      }`}
      {...props}
    >
      {icon}
      {children}
    </button>
  );
};
