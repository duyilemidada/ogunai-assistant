import { useState } from 'react'
import Layout from '../components/Layout'
import Tabs from '../components/ui/Tabs'
import DocumentsList from '../components/memory/DocumentsList'
import LearningProgressList from '../components/memory/LearningProgressList'

const TABS = [
  { key: 'documents', label: 'Documents' },
  { key: 'learning', label: 'Learning Progress' },
]

export default function MemoryPage() {
  const [active, setActive] = useState('documents')

  return (
    <Layout>
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto">
          <div className="px-4 pt-6 pb-2">
            <h1 className="text-xl font-bold text-text-primary">Memory</h1>
            <p className="text-text-muted text-sm mt-1">
              What Ogun AI has stored about your documents and learning.
            </p>
          </div>
          <Tabs tabs={TABS} active={active} onChange={setActive} />
          {active === 'documents' ? (
            <DocumentsList />
          ) : (
            <LearningProgressList />
          )}
        </div>
      </div>
    </Layout>
  )
}
