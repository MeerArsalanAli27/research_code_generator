interface SplineSceneProps {
  scene?: string;
  className?: string;
}

const SplineScene = ({ className = "" }: SplineSceneProps) => {
  return (
    <div className={`w-full h-full ${className}`}>
      <div className="w-full h-full flex items-center justify-center text-sm text-muted-foreground">
        3D preview is temporarily disabled for compatibility.
      </div>
    </div>
  );
};

export default SplineScene;