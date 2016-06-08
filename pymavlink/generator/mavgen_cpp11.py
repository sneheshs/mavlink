#!/usr/bin/env python
'''
parse a MAVLink protocol XML file and generate a C++ implementation

Based on C implementation and require C-library for framing.

Copyright Andrew Tridgell 2011
Copyright Vladimir Ermakov 2016
Released under GNU GPL version 3 or later
'''

import sys, textwrap, os, time
from . import mavparse, mavtemplate

t = mavtemplate.MAVTemplate()


def generate_main_hpp(directory, xml):
    '''generate main header per XML file'''
    f = open(os.path.join(directory, xml.basename + ".hpp"), mode='w')
    t.write(f, '''
/** @file
 *	@brief MAVLink comm protocol generated from ${basename}.xml
 *	@see http://mavlink.org
 */

#pragma once

#include <array>
#include <cstdint>
#include <sstream>

#ifndef MAVLINK_STX
#define MAVLINK_STX ${protocol_marker}
#endif

#include "../message.hpp"

namespace mavlink {
namespace ${basename} {

/**
 * Array of msg_entry needed for @p mavlink_parse_char() (trought @p mavlink_get_msg_entry())
 */
constexpr std::array<mavlink_msg_entry_t, ${message_entry_len}> MESSAGE_ENTRIES {{ ${message_entry_array} }};

//! MAVLINK VERSION
constexpr auto MAVLINK_VERSION = ${version};


// ENUM DEFINITIONS

${{enum:
/** @brief ${description} */
enum class ${name} : int
{
${{entry:    ${name_trim}=${value}, /* ${description} |${{param:${description}| }} */
}}
};
}}


} // namespace ${basename}
} // namespace mavlink

// MESSAGE DEFINITIONS
${{message:#include "./mavlink_msg_${name_lower}.hpp"
}}

// base include
${{include_list:#include "../${base}/${base}.hpp"
}}
''', xml)

    f.close()


def generate_message_hpp(directory, m):
    '''generate per-message header for a XML file'''
    f = open(os.path.join(directory, 'mavlink_msg_%s.hpp' % m.name_lower), mode='w')
    t.write(f, '''
// MESSAGE ${name} support class

#pragma once

namespace mavlink {
namespace ${dialect_name} {
namespace msg {

/**
 * @brief ${name} message
 *
 * ${description}
 */
struct ${name} : mavlink::Message {
    static constexpr uint32_t MSG_ID = ${id};
    static constexpr size_t LENGTH = ${wire_length};
    static constexpr size_t MIN_LENGTH = ${wire_min_length};
    static constexpr uint8_t CRC_EXTRA = ${crc_extra};
    static constexpr auto NAME = "${name}";


${{fields:    ${cxx_type} ${name}; /*< ${description} */
}}


    inline std::string to_yaml(void) const
    {
        std::stringstream ss;

        ss << NAME << ":" << std::endl;
${{fields:        ${to_yaml_code}
}}

        return ss.str();
    }

    inline void serialize(mavlink::MsgMap &map) const
    {
        map.reset(MSG_ID, LENGTH);

${{ordered_fields:        map << ${ser_name};${ser_whitespace}// offset: ${wire_offset}
}}
    }

    inline void deserialize(mavlink::MsgMap &map)
    {
${{ordered_fields:        map >> ${name};${ser_whitespace}// offset: ${wire_offset}
}}
    }
};

} // namespace msg
} // namespace ${dialect_name}
} // namespace mavlink
''', m)
    f.close()


def generate_gtestsuite_hpp(directory, xml):
    '''generate gtestsuite.hpp per XML file'''
    f = open(os.path.join(directory, "gtestsuite.hpp"), mode='w')
    t.write(f, '''
/** @file
 *	@brief MAVLink comm testsuite protocol generated from ${basename}.xml
 *	@see http://mavlink.org
 */

#pragma once

#include <gtest/gtest.h>
#include "${basename}.hpp"

#ifdef TEST_INTEROP
using namespace mavlink;
#undef MAVLINK_HELPER
#include "mavlink.h"
#endif

${{message:
TEST(${dialect_name}, ${name})
{
    mavlink::mavlink_message_t msg;
    mavlink::MsgMap map1(msg);
    mavlink::MsgMap map2(msg);

    mavlink::${dialect_name}::msg::${name} packet_in{};
${{fields:    packet_in.${name} = ${cxx_test_value};
}}

    mavlink::${dialect_name}::msg::${name} packet1{};
    mavlink::${dialect_name}::msg::${name} packet2{};

    packet1 = packet_in;

    //std::cout << packet1.to_yaml() << std::endl;

    packet1.serialize(map1);

    mavlink::mavlink_finalize_message(&msg, 1, 1, packet1.MIN_LENGTH, packet1.LENGTH, packet1.CRC_EXTRA);

    packet2.deserialize(map2);

${{fields:    EXPECT_EQ(packet1.${name}, packet2.${name});
}}
}

#ifdef TEST_INTEROP
TEST(${dialect_name}_interop, ${name})
{
    mavlink_message_t msg;
    MsgMap map2(msg);

    // to get nice print
    memset(&msg, 0, sizeof(msg));

    mavlink_${name_lower}_t packet_c {
        ${{ordered_fields: ${c_test_value},}}
    };

    mavlink::${dialect_name}::msg::${name} packet_in{};
${{fields:    packet_in.${name} = ${cxx_test_value};
}}

    mavlink::${dialect_name}::msg::${name} packet2{};

    mavlink_msg_${name_lower}_encode(1, 1, &msg, &packet_c);

    packet2.deserialize(map2);

${{fields:    EXPECT_EQ(packet_in.${name}, packet2.${name});
}}

#ifdef PRINT_MSG
    PRINT_MSG(msg);
#endif
}
#endif
}}
''', xml)

    f.close()



def copy_fixed_headers(directory, xml):
    '''copy the fixed protocol headers to the target directory'''
    import shutil, filecmp
    hlist = {
        "2.0": ['message.hpp', 'msgmap.hpp']
        }
    basepath = os.path.dirname(os.path.realpath(__file__))
    srcpath = os.path.join(basepath, 'CPP11/include_v%s' % xml.wire_protocol_version)
    print("Copying fixed headers for protocol %s to %s" % (xml.wire_protocol_version, directory))
    for h in hlist[xml.wire_protocol_version]:
        src = os.path.realpath(os.path.join(srcpath, h))
        dest = os.path.realpath(os.path.join(directory, h))
        if src == dest or (os.path.exists(dest) and filecmp.cmp(src, dest)):
            continue
        shutil.copy(src, dest)


class mav_include(object):
    def __init__(self, base):
        self.base = base


def enum_remove_prefix(prefix, s):
    '''remove prefix from enum entry'''
    pl = prefix.split('_')
    sl = s.split('_')

    for i in range(len(pl)):
        if pl[i] == sl[0]:
            sl = sl[1:]
        else:
            break

    if sl[0][0].isdigit():
        sl.insert(0, pl[-1])

    return '_'.join(sl)


def generate_one(basename, xml):
    '''generate headers for one XML file'''

    directory = os.path.join(basename, xml.basename)

    print("Generating C++ implementation in directory %s" % directory)
    mavparse.mkdir_p(directory)

    if xml.wire_protocol_version != mavparse.PROTOCOL_2_0:
        raise ValueError("C++ implementation only support --wire-protocol=2.0")

    # work out the included headers
    xml.include_list = []
    for i in xml.include:
        base = i[:-4]
        xml.include_list.append(mav_include(base))

    # and message metadata array
    # we sort with primary key msgid
    xml.message_entry_len = len(xml.message_crcs)
    xml.message_entry_array = ', '.join([
        '{%u, %u, %u, %u, %u, %u}' % (
            msgid,
            xml.message_crcs[msgid],
            xml.message_min_lengths[msgid],
            xml.message_flags[msgid],
            xml.message_target_system_ofs[msgid],
            xml.message_target_component_ofs[msgid])
        for msgid in sorted(xml.message_crcs.keys())])

    # add trimmed filed name to enums
    for e in xml.enum:
        for f in e.entry:
            f.name_trim = enum_remove_prefix(e.name, f.name)

    # add some extra field attributes for convenience with arrays
    for m in xml.message:
        m.dialect_name = xml.basename
        m.msg_name = m.name

        for f in m.fields:
            spaces = 30 - len(f.name)
            f.ser_whitespace = ' ' * (spaces if spaces > 1 else 1)
            f.ser_name = f.name  # for most of fields it is name

            to_yaml_cast = 'int' if f.type in ['uint8_t', 'int8_t'] else ''

            # XXX use TIMESYNC message to test trimmed message decoding
            if m.name == 'TIMESYNC' and f.name == 'ts1':
                f.test_value = 0xAA

            if f.array_length != 0:
                f.cxx_type = 'std::array<%s, %s>' % (f.type, f.array_length)
                f.to_yaml_code = """ss << "  %s: ["; for (auto &_v : %s) { ss << %s(_v) << ", "; }; ss << "]" << std::endl;""" % (
                    f.name, f.name, to_yaml_cast)

                if f.type == 'char':
                    # XXX find how to make std::array<> from const char[]
                    f.cxx_test_value = 'make_str_array(packet_in.%s, "%s")' % (f.name, f.test_value)
                    f.c_test_value = '"%s"' % f.test_value
                else:
                    f.cxx_test_value = '{ %s }' % ', '.join([str(v) for v in f.test_value])
                    f.c_test_value = f.cxx_test_value
            else:
                f.cxx_type = f.type
                f.to_yaml_code = """ss << "  %s: " << %s(%s) << std::endl;""" % (f.name, to_yaml_cast, f.name)

                # XXX sometime test_value is > 127 for int8_t, monkeypatch
                if f.type == 'int8_t' and f.test_value > 127:
                    f.test_value -= 128;

                if f.type == 'char':
                    f.cxx_test_value = "'%s'" % f.test_value
                elif f.type == 'int64_t':
                    f.cxx_test_value = "%sLL" % f.test_value
                elif f.type == 'uint64_t':
                    f.cxx_test_value = "%sULL" % f.test_value
                else:
                    f.cxx_test_value = f.test_value

                f.c_test_value = f.cxx_test_value


            # cope with uint8_t_mavlink_version
            if f.omit_arg:
                f.ser_name = "%s(%s)" % (f.type, f.const_value)

    generate_main_hpp(directory, xml)
    for m in xml.message:
        generate_message_hpp(directory, m)
    generate_gtestsuite_hpp(directory, xml)


def generate(basename, xml_list):
    '''generate serialization MAVLink C++ implemenation'''

    for xml in xml_list:
        generate_one(basename, xml)
    copy_fixed_headers(basename, xml_list[0])
