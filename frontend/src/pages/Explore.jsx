import LogExplorer from '../components/LogExplorer'

function Explore() {
  return (
    <div className="py-8">
      <div className="mb-8">
        <h1 className="text-4xl font-black tracking-tight mb-2">
          Log Explorer
        </h1>
        <p className="text-neutral-400 max-w-2xl">
          Search logs semantically and get AI-powered root cause analysis for any error.
        </p>
      </div>
      <LogExplorer />
    </div>
  )
}

export default Explore
