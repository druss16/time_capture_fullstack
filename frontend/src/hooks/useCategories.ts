// src/hooks/useCategories.ts
/**
 * Hook to fetch industry-specific categories for the current org.
 * Use this anywhere you need the category dropdown.
 */

import { useState, useEffect, useCallback } from 'react';
import { safeFetchJson } from '@/lib/api';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

// Fallback categories if API fails
const FALLBACK_CATEGORIES = [
  "Tax Preparation", "Tax Planning", "Tax Research", "Tax Compliance",
  "Accounting/Bookkeeping", "Financial Statement Prep", "Audit/Assurance",
  "Payroll Services", "Advisory/Financial Planning", "Software Development",
  "Research/AI Assistance", "Email/Communication", "Meetings", 
  "Administration", "Documentation", "Review", "Idle",
];

interface UseCategoriesResult {
  categories: string[];
  industryType: string;
  industryName: string;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export function useCategories(): UseCategoriesResult {
  const [categories, setCategories] = useState<string[]>(FALLBACK_CATEGORIES);
  const [industryType, setIndustryType] = useState<string>('general');
  const [industryName, setIndustryName] = useState<string>('General');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchCategories = useCallback(async () => {
    setLoading(true);
    setError(null);
    
    try {
      const data = await safeFetchJson<{
        categories: string[];
        industry_type: string;
        industry_name: string;
      }>(`${API_BASE}/categories/`);
      
      if (data?.categories?.length) {
        setCategories(data.categories);
        setIndustryType(data.industry_type || 'general');
        setIndustryName(data.industry_name || 'General');
      }
    } catch (err: any) {
      console.warn('[useCategories] Failed to fetch, using fallback:', err);
      setError(err?.message || 'Failed to load categories');
      // Keep fallback categories
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCategories();
  }, [fetchCategories]);

  return {
    categories,
    industryType,
    industryName,
    loading,
    error,
    refetch: fetchCategories,
  };
}

export default useCategories;