import React from 'react'
import { shallow, configure } from 'enzyme'
import Adapter from 'enzyme-adapter-react-16'
import { getUser } from 'redux/selectors'
import { getProject } from '../selectors'
import { PageHeader } from './PageHeader'


import { STATE_WITH_2_FAMILIES } from '../fixtures'

configure({ adapter: new Adapter() })

test('shallow-render without crashing', () => {
  /*
    project: PropTypes.object.isRequired,
   */

  const props = {
    user: getUser(STATE_WITH_2_FAMILIES),
    project: getProject(STATE_WITH_2_FAMILIES),
    match: { params: { breadcrumb: 'a_page' } },
  }

  shallow(<PageHeader {...props} />)
})
