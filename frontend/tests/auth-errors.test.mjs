import assert from 'node:assert/strict'
import test from 'node:test'
import { AuthApiError } from '@supabase/supabase-js'
import { emailSignInError } from '../src/auth-client.ts'

test('email quota exhaustion asks the user to wait rather than change the email', () => {
  const message = emailSignInError(new AuthApiError('Email rate limit exceeded', 429, 'over_email_send_rate_limit'))
  assert.match(message, /حد المؤقت لإرسال رسائل التحقق/)
  assert.match(message, /انتظر/)
  assert.doesNotMatch(message, /تأكد من الإيميل/)
})

test('request throttling and an uncoded 429 ask the user to wait', () => {
  for (const error of [new AuthApiError('Request limit exceeded', 429, 'over_request_rate_limit'), new AuthApiError('Too many requests', 429)]) {
    assert.match(emailSignInError(error), /انتظر/)
  }
})

test('invalid email and unapproved recipient have distinct guidance', () => {
  assert.match(emailSignInError(new AuthApiError('Invalid email', 422, 'email_address_invalid')), /عنوان الإيميل غير مقبول/)
  assert.match(emailSignInError(new AuthApiError('Email not authorized', 400, 'email_address_not_authorized')), /لهذا الإيميل غير متاح/)
})

test('network and unknown failures do not expose upstream messages or blame the email', () => {
  for (const error of [new TypeError('Failed to fetch'), new Error('private upstream detail'), null, 'private upstream detail']) {
    const message = emailSignInError(error)
    assert.match(message, /تابع كضيف/)
    assert.doesNotMatch(message, /private|تأكد من الإيميل/)
  }
})
