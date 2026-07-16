import { Flex, Heading, HStack, Link as ChakraLink } from '@chakra-ui/react'
import { NavLink } from 'react-router'

const linkStyle = ({ isActive }: { isActive: boolean }) => ({
  fontWeight: isActive ? 700 : 400,
  textDecoration: isActive ? 'underline' : 'none',
})

export function NavBar() {
  return (
    <Flex as="nav" borderBottomWidth="1px" px={6} py={3} align="center" gap={6}>
      <Heading size="md">RAG Document Assistant</Heading>
      <HStack gap={4} ml="auto">
        <ChakraLink asChild>
          <NavLink to="/" end style={linkStyle}>
            Chat
          </NavLink>
        </ChakraLink>
        <ChakraLink asChild>
          <NavLink to="/upload" style={linkStyle}>
            Upload
          </NavLink>
        </ChakraLink>
      </HStack>
    </Flex>
  )
}
