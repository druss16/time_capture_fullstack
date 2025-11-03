import { Link } from "react-router-dom";
import { Clock, TrendingUp, CheckCircle, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

const Index = () => {
  return (
    <div className="min-h-screen bg-gradient-subtle">
      {/* Hero Section */}
      <div className="container mx-auto px-4 py-16">
        <div className="text-center max-w-3xl mx-auto mb-12">
          <div className="flex items-center justify-center gap-3 mb-6">
            <div className="flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-primary shadow-elevated">
              <Clock className="w-8 h-8 text-white" />
            </div>
          </div>
          
          <h1 className="text-5xl font-bold text-foreground mb-4">
            TimeTrack Pro
          </h1>
          <p className="text-xl text-muted-foreground mb-8">
            Professional time tracking and classification built specifically for CPAs. 
            Smart AI-powered categorization saves you hours every week.
          </p>
          
          <Link to="/daily-review">
            <Button size="lg" className="text-lg px-8 h-12 shadow-elevated">
              Open Daily Review
              <ArrowRight className="ml-2 w-5 h-5" />
            </Button>
          </Link>
        </div>

        {/* Features */}
        <div className="grid md:grid-cols-3 gap-6 max-w-5xl mx-auto">
          <div className="bg-card p-6 rounded-xl shadow-card border hover:shadow-elevated transition-all duration-200">
            <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
              <TrendingUp className="w-6 h-6 text-primary" />
            </div>
            <h3 className="font-semibold text-lg mb-2 text-foreground">AI-Powered Classification</h3>
            <p className="text-muted-foreground text-sm">
              Automatically categorize time blocks by client, project, and billing categories with high accuracy.
            </p>
          </div>

          <div className="bg-card p-6 rounded-xl shadow-card border hover:shadow-elevated transition-all duration-200">
            <div className="w-12 h-12 rounded-lg bg-secondary/10 flex items-center justify-center mb-4">
              <Clock className="w-6 h-6 text-secondary" />
            </div>
            <h3 className="font-semibold text-lg mb-2 text-foreground">Real-Time Tracking</h3>
            <p className="text-muted-foreground text-sm">
              Track every minute of your workday automatically with precise time blocks and activity monitoring.
            </p>
          </div>

          <div className="bg-card p-6 rounded-xl shadow-card border hover:shadow-elevated transition-all duration-200">
            <div className="w-12 h-12 rounded-lg bg-success/10 flex items-center justify-center mb-4">
              <CheckCircle className="w-6 h-6 text-success" />
            </div>
            <h3 className="font-semibold text-lg mb-2 text-foreground">Easy Review & Export</h3>
            <p className="text-muted-foreground text-sm">
              Review your day at a glance, make corrections, and export to CSV for seamless billing integration.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Index;
